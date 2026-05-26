import { createRouter, createWebHistory } from "vue-router";

import AuthView from "./views/AuthView.vue";
import WorkspaceView from "./views/WorkspaceView.vue";
import { useAuthStore } from "./stores/auth";

const router = createRouter({
  history: createWebHistory(),
  routes: [
    {
      path: "/",
      redirect: "/app",
    },
    {
      path: "/auth",
      name: "auth",
      component: AuthView,
    },
    {
      path: "/app",
      name: "workspace",
      component: WorkspaceView,
      meta: { requiresAuth: true },
    },
  ],
});

router.beforeEach(async (to) => {
  const auth = useAuthStore();
  if (!auth.ready) {
    await auth.initialize();
  }

  if (to.meta.requiresAuth && !auth.isAuthenticated) {
    return { name: "auth" };
  }

  if (to.name === "auth" && auth.isAuthenticated) {
    return { name: "workspace" };
  }

  return true;
});

export default router;
