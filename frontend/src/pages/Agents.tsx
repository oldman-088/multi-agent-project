import { useEffect, useState } from 'react';
import type { FormEvent } from 'react';
import { ApiError, apiClient } from '../api/client';
import type { Agent } from '../api/client';

export function AgentsPage() {
  const [agents, setAgents] = useState<Agent[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [formOpen, setFormOpen] = useState(false);
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    let active = true;
    apiClient.listAgents()
      .then((items) => { if (active) setAgents(items); })
      .catch((cause: unknown) => { if (active) setError(errorMessage(cause)); })
      .finally(() => { if (active) setLoading(false); });
    return () => { active = false; };
  }, []);

  async function createAgent(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = event.currentTarget;
    const data = new FormData(form);
    const name = String(data.get('name') ?? '').trim();
    const goal = String(data.get('goal') ?? '').trim();
    const runtime = String(data.get('runtime') ?? 'native');
    if (!name || !goal) {
      setError('Name and goal are required.');
      return;
    }

    setSaving(true);
    setError('');
    try {
      const agent = await apiClient.createAgent({ name, goal, runtime });
      setAgents((current) => [...current, agent]);
      setFormOpen(false);
      form.reset();
    } catch (cause: unknown) {
      setError(errorMessage(cause));
    } finally {
      setSaving(false);
    }
  }

  return (
    <main className="page" aria-labelledby="agents-heading">
      <header className="page-header">
        <div>
          <p className="eyebrow">Workspace</p>
          <h1 id="agents-heading" data-testid="agents-heading">Agents</h1>
          <p className="muted">Create and manage agents and their runtime configuration.</p>
        </div>
        <button data-testid="create-agent-button" type="button" onClick={() => { setFormOpen(true); setError(''); }}>
          Create agent
        </button>
      </header>

      {error && <p className="error" role="alert">{error}</p>}

      {formOpen && (
        <form className="panel form-grid" onSubmit={createAgent} aria-label="Create agent">
          <h2>Create agent</h2>
          <label htmlFor="agent-name">Name</label>
          <input id="agent-name" name="name" data-testid="agent-name-input" required maxLength={120} autoFocus />
          <label htmlFor="agent-goal">Goal</label>
          <textarea id="agent-goal" name="goal" data-testid="agent-goal-input" required rows={3} />
          <label htmlFor="agent-runtime">Runtime</label>
          <select id="agent-runtime" name="runtime" data-testid="agent-runtime-select" defaultValue="native">
            <option value="native">Native</option>
            <option value="langgraph">LangGraph</option>
          </select>
          <div className="form-actions">
            <button type="submit" data-testid="save-agent-button" disabled={saving}>
              {saving ? 'Saving…' : 'Save agent'}
            </button>
            <button type="button" className="secondary" onClick={() => setFormOpen(false)}>Cancel</button>
          </div>
        </form>
      )}

      {loading ? <p role="status">Loading agents…</p> : agents.length === 0 ? (
        <section className="panel empty-state"><h2>No agents yet</h2><p>Create an agent to get started.</p></section>
      ) : (
        <ul className="agent-list" aria-label="Agents">
          {agents.map((agent) => (
            <li className="panel agent-row" data-testid="agent-row" key={agent.id}>
              <div>
                <h2>{agent.name}</h2>
                <p className="muted">{agent.goal || agent.description || 'No goal provided.'}</p>
              </div>
              <span className="badge">{agent.runtime ?? 'native'}</span>
            </li>
          ))}
        </ul>
      )}
    </main>
  );
}

function errorMessage(cause: unknown): string {
  return cause instanceof ApiError ? cause.message : 'Unable to load agents. Please try again.';
}
