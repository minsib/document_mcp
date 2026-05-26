import { createApp } from "vue";
import { createPinia } from "pinia";

import App from "./App.vue";
import router from "./router";
import { useUiStore } from "./stores/ui";
import "./styles.css";
import "@vueup/vue-quill/dist/vue-quill.snow.css";

const app = createApp(App);
const pinia = createPinia();

app.use(pinia);
useUiStore(pinia).initializeTheme();
app.use(router);
app.mount("#app");
