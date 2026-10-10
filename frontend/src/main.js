import { createApp } from 'vue'
import { createPinia } from 'pinia'
import App from './App.vue'
import { useUiStore } from './stores/ui'
import 'markstream-vue/index.css' // 代码块/语言图标/表格等尺寸规则来源；必须在 theme 之前，让主题可覆盖
import './styles/theme.css'

const pinia = createPinia()
const app = createApp(App).use(pinia)

// paint the stored theme before the first render: switching schemes must never
// flash white (styles/theme.css keys every token off html[data-theme])
const ui = useUiStore(pinia)
ui.applyTheme()
ui.watchSystemTheme()

app.mount('#app')
