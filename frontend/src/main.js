import { createApp } from 'vue'
import { createPinia } from 'pinia'
import App from './App.vue'
import { useUiStore } from './stores/ui'
import './styles/theme.css'

const pinia = createPinia()
const app = createApp(App).use(pinia)

// paint the stored theme before the first render: switching schemes must never
// flash white (styles/theme.css keys every token off html[data-theme])
const ui = useUiStore(pinia)
ui.applyTheme()
ui.watchSystemTheme()

app.mount('#app')
