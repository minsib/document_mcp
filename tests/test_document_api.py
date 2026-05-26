from __future__ import annotations

import requests

def test_register_login_and_profile(
    client: requests.Session,
    api_base_url: str,
    auth_context,
    auth_headers: dict[str, str],
) -> None:
    response = client.get(
        f"{api_base_url}/v1/auth/me",
        headers=auth_headers,
        timeout=15,
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["username"] == auth_context.username
    assert payload["email"] == auth_context.email
    assert payload["is_active"] is True


def test_markdown_upload_export_and_pdf_rejection(
    client: requests.Session,
    api_base_url: str,
    auth_headers: dict[str, str],
    uploaded_markdown_doc: dict[str, str],
) -> None:
    doc_id = uploaded_markdown_doc["doc_id"]
    documents_response = client.get(
        f"{api_base_url}/v1/docs",
        headers=auth_headers,
        timeout=15,
    )

    export_response = client.get(
        f"{api_base_url}/v1/docs/{doc_id}/export",
        headers=auth_headers,
        timeout=15,
    )
    revisions_response = client.get(
        f"{api_base_url}/v1/docs/{doc_id}/revisions",
        headers=auth_headers,
        timeout=15,
    )
    pdf_response = client.post(
        f"{api_base_url}/v1/docs/upload",
        data={"title": "Pytest PDF"},
        files={"file": ("sample.pdf", b"%PDF-1.4 fake", "application/pdf")},
        headers=auth_headers,
        timeout=15,
    )

    assert documents_response.status_code == 200
    documents_payload = documents_response.json()
    assert documents_payload["total"] >= 1
    assert any(item["doc_id"] == doc_id for item in documents_payload["documents"])

    assert export_response.status_code == 200
    export_payload = export_response.json()
    assert "FastAPI + PostgreSQL" in export_payload["content"]

    assert revisions_response.status_code == 200
    revisions_payload = revisions_response.json()
    assert revisions_payload["total"] == 1
    assert revisions_payload["revisions"][0]["is_active"] is True

    assert pdf_response.status_code == 400
    assert "暂不支持 PDF 解析" in pdf_response.text


def test_docx_upload_and_export(
    client: requests.Session,
    api_base_url: str,
    auth_headers: dict[str, str],
    docx_bytes: bytes,
) -> None:
    upload_response = client.post(
        f"{api_base_url}/v1/docs/upload",
        data={"title": "Pytest DOCX"},
        files={
            "file": (
                "sample.docx",
                docx_bytes,
                "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            )
        },
        headers=auth_headers,
        timeout=20,
    )

    assert upload_response.status_code == 200
    upload_payload = upload_response.json()
    assert upload_payload["block_count"] >= 3

    export_response = client.get(
        f"{api_base_url}/v1/docs/{upload_payload['doc_id']}/export",
        headers=auth_headers,
        timeout=15,
    )

    assert export_response.status_code == 200
    content = export_response.json()["content"]
    assert "DOCX 测试文档" in content
    assert "这是一个用于验证 DOCX 转 Markdown 的测试段落。" in content
    assert "第一项" in content
    assert "第二项" in content


def test_docx_upload_uses_filename_when_title_missing(
    client: requests.Session,
    api_base_url: str,
    auth_headers: dict[str, str],
    docx_bytes: bytes,
) -> None:
    upload_response = client.post(
        f"{api_base_url}/v1/docs/upload",
        files={
            "file": (
                "需求说明.docx",
                docx_bytes,
                "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            )
        },
        headers=auth_headers,
        timeout=20,
    )

    assert upload_response.status_code == 200
    upload_payload = upload_response.json()
    assert upload_payload["title"] == "需求说明"

    documents_response = client.get(
        f"{api_base_url}/v1/docs",
        headers=auth_headers,
        timeout=15,
    )

    assert documents_response.status_code == 200
    assert any(
        item["doc_id"] == upload_payload["doc_id"] and item["title"] == "需求说明"
        for item in documents_response.json()["documents"]
    )


def test_update_document_content_creates_new_revision(
    client: requests.Session,
    api_base_url: str,
    auth_headers: dict[str, str],
    uploaded_markdown_doc: dict[str, str],
) -> None:
    doc_id = uploaded_markdown_doc["doc_id"]
    update_response = client.put(
        f"{api_base_url}/v1/docs/{doc_id}/content",
        json={
            "content": (
                "# 项目需求文档\n\n"
                "## 技术架构\n\n"
                "系统采用 Django + PostgreSQL 架构。\n\n"
                "## 核心功能\n\n"
                "支持对话式编辑与版本回滚。"
            ),
            "change_summary": "编辑器保存测试",
        },
        headers=auth_headers,
        timeout=20,
    )

    assert update_response.status_code == 200
    update_payload = update_response.json()
    assert update_payload["rev_no"] == 2
    assert update_payload["version"] == 2

    export_response = client.get(
        f"{api_base_url}/v1/docs/{doc_id}/export",
        headers=auth_headers,
        timeout=15,
    )
    revisions_response = client.get(
        f"{api_base_url}/v1/docs/{doc_id}/revisions",
        headers=auth_headers,
        timeout=15,
    )

    assert export_response.status_code == 200
    export_payload = export_response.json()
    assert "Django + PostgreSQL" in export_payload["content"]
    assert "版本回滚" in export_payload["content"]

    assert revisions_response.status_code == 200
    revisions_payload = revisions_response.json()
    assert revisions_payload["total"] == 2
    assert revisions_payload["revisions"][0]["change_summary"] == "编辑器保存测试"
