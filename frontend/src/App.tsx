import { AgentsPage } from './pages/Agents';
import { ChatPage } from './pages/Chat';
import './styles.css';

export function App() {
  const path = window.location.pathname.replace(/\/$/, '') || '/';
  if (path === '/agents') return <AgentsPage />;
  return <ChatPage />;
}
