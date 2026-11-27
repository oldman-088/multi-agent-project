import { StrictMode } from 'react';
import { createRoot } from 'react-dom/client';
import App from './App';
import { initI18n } from './i18n';
import './styles/index.css';

async function bootstrap() {
  await initI18n();
  const container = document.getElementById('root');
  if (!container) {
    throw new Error('Root container #root not found');
  }
  createRoot(container).render(
    <StrictMode>
      <App />
    </StrictMode>,
  );
}

void bootstrap();
