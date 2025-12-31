import { createApp } from 'vue'
import { createPinia } from 'pinia'
import "./style.css"
import App from './App.vue'

const app = createApp(App)
app.use(createPinia())
app.mount('#app').$nextTick(() => {
  // Use contextBridge
  window.ipcRenderer.on('main-process-message', (_event, message) => {
    console.log(message)
  })
})
