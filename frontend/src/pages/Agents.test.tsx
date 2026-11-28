import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { apiClient } from '../api/client';
import { AgentsPage } from './Agents';

vi.mock('../api/client', () => ({
  ApiError: class ApiError extends Error {},
  apiClient: { listAgents: vi.fn(), createAgent: vi.fn(), listAgentVersions: vi.fn() },
}));

const listAgents = vi.mocked(apiClient.listAgents);
const createAgent = vi.mocked(apiClient.createAgent);

beforeEach(() => {
  listAgents.mockReset();
  createAgent.mockReset();
});

describe('AgentsPage', () => {
  it('loads and renders agents from apiClient', async () => {
    listAgents.mockResolvedValue([{ id: 'a1', name: 'Researcher', goal: 'Find reliable answers', runtime: 'native' }]);
    render(<AgentsPage />);

    expect(await screen.findByText('Researcher')).toBeInTheDocument();
    expect(screen.getByText('Find reliable answers')).toBeInTheDocument();
  });

  it('validates and creates an agent, then updates the list', async () => {
    const user = userEvent.setup();
    listAgents.mockResolvedValue([]);
    createAgent.mockResolvedValue({ id: 'a2', name: 'Writer', goal: 'Write clearly', runtime: 'native' });
    render(<AgentsPage />);

    await user.click(await screen.findByTestId('create-agent-button'));
    await user.type(screen.getByTestId('agent-name-input'), 'Writer');
    await user.type(screen.getByTestId('agent-goal-input'), 'Write clearly');
    await user.click(screen.getByTestId('save-agent-button'));

    await waitFor(() => expect(createAgent).toHaveBeenCalledWith({ name: 'Writer', goal: 'Write clearly', runtime: 'native' }));
    expect(await screen.findByText('Writer')).toBeInTheDocument();
  });
});
