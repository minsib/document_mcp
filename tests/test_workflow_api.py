from __future__ import annotations

import uuid

import requests


ALLOWED_EDIT_STATUSES = {
    "need_disambiguation",
    "need_confirm",
    "need_clarification",
    "applied",
}


def test_chat_edit_persists_session_and_exposes_metrics(
    client: requests.Session,
    api_base_url: str,
    auth_headers: dict[str, str],
    uploaded_markdown_doc: dict[str, str],
) -> None:
    raw_session_id = str(uuid.uuid4())
    response = client.post(
        f"{api_base_url}/v1/chat/edit",
        json={
            "doc_id": uploaded_markdown_doc["doc_id"],
            "session_id": raw_session_id,
            "message": "把技术架构那段的 FastAPI 改成 Django",
        },
        headers=auth_headers,
        timeout=60,
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] in ALLOWED_EDIT_STATUSES
    assert payload["status"] != "failed"
    assert payload["session_id"]

    session_response = client.get(
        f"{api_base_url}/v1/chat/sessions/{payload['session_id']}",
        headers=auth_headers,
        timeout=20,
    )
    assert session_response.status_code == 200
    session_payload = session_response.json()
    assert session_payload["session_id"] == payload["session_id"]
    assert len(session_payload["messages"]) == 2
    assert session_payload["messages"][0]["role"] == "user"
    assert session_payload["messages"][0]["content"] == "把技术架构那段的 FastAPI 改成 Django"
    assert session_payload["messages"][1]["role"] == "assistant"
    assert session_payload["messages"][1]["meta"]["status"] == payload["status"]

    metrics_response = client.get(f"{api_base_url}/metrics/", timeout=20)
    assert metrics_response.status_code == 200
    metrics_text = metrics_response.text
    for metric_name in [
        "workflow_node_total",
        "workflow_route_total",
        "retrieval_candidate_count",
        "retrieval_selected_confidence",
        "retrieval_resolution_total",
        "retrieval_evidence_validation_total",
    ]:
        assert metric_name in metrics_text


def test_bulk_edit_preview_confirm_and_revision_export(
    client: requests.Session,
    api_base_url: str,
    auth_headers: dict[str, str],
    uploaded_bulk_doc: dict[str, str],
) -> None:
    preview_response = client.post(
        f"{api_base_url}/v1/chat/bulk-edit",
        json={
            "session_id": "bulk-replace-suite",
            "doc_id": uploaded_bulk_doc["doc_id"],
            "message": "将所有旧词替换为新词",
            "match_type": "exact_term",
            "scope_filter": {
                "term": "旧词",
                "replacement": "新词",
            },
        },
        headers=auth_headers,
        timeout=30,
    )

    assert preview_response.status_code == 200
    preview_payload = preview_response.json()
    assert preview_payload["status"] == "need_confirm"
    assert preview_payload["preview"]["total_changes"] >= 2
    assert preview_payload["confirm_token"]
    assert preview_payload["preview_hash"]

    confirm_response = client.post(
        f"{api_base_url}/v1/chat/bulk-confirm",
        json={
            "session_id": preview_payload["session_id"],
            "doc_id": uploaded_bulk_doc["doc_id"],
            "confirm_token": preview_payload["confirm_token"],
            "preview_hash": preview_payload["preview_hash"],
            "action": "apply",
        },
        headers=auth_headers,
        timeout=30,
    )

    assert confirm_response.status_code == 200
    confirm_payload = confirm_response.json()
    assert confirm_payload["status"] == "applied"
    assert confirm_payload["new_rev_id"]

    export_response = client.get(
        f"{api_base_url}/v1/docs/{uploaded_bulk_doc['doc_id']}/export",
        headers=auth_headers,
        timeout=20,
    )
    assert export_response.status_code == 200
    content = export_response.json()["content"]
    assert "新词" in content
    assert "旧词" not in content

    revisions_response = client.get(
        f"{api_base_url}/v1/docs/{uploaded_bulk_doc['doc_id']}/revisions",
        headers=auth_headers,
        timeout=20,
    )
    assert revisions_response.status_code == 200
    revisions_payload = revisions_response.json()
    assert revisions_payload["total"] >= 2
