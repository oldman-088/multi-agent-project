import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { apiClient } from '../api/client';
import { ChatPage } from './Chat';

vi.mock('../api/client', () => ({
  ApiError: class ApiError extends Error {},
  apiClient: {
    listConversations: vi.fn(), createConversation: vi.fn(), listMessages: vi.fn(),
    sendMessage: vi.fn(), subscribeToRun: vi.fn(),
  },
}));

const client = vi.mocked(apiClient);

beforeEach(() => {
  client.listConversations.mockReset();
  client.createConversation.mockReset();
  client.listMessages.mockReset();
  client.sendMessage.mockReset();
  client.subscribeToRun.mockReset();
  client.listConversations.mockResolvedValue([{ id: 'c1', title: 'Project chat' }]);
  client.listMessages.mockResolvedValue([{ id: 'm1', role: 'assistant', content: 'Welcome back.' }]);
});

describe('ChatPage', () => {
  it('loads persisted conversation history through apiClient', async () => {
    render(<ChatPage />);
    expect(await screen.findByText('Welcome back.')).toBeInTheDocument();
    expect(client.listMessages).toHaveBeenCalledWith('c1');
  });

  it('posts a message through apiClient and renders the response', async () => {
    const user = userEvent.setup();
    client.sendMessage.mockResolvedValue({ id: 'm2', role: 'user', content: 'Hello agent' });
    render(<ChatPage />);

    const input = await screen.findByTestId('message-input');
    await user.type(input, 'Hello agent');
    await user.click(screen.getByTestId('send-button'));

    await waitFor(() => expect(client.sendMessage).toHaveBeenCalledWith('c1', 'Hello agent'));
    expect(await screen.findByText('Hello agent')).toBeInTheDocument();
  });

  it('creates a conversation when no conversation exists yet', async () => {
    client.listConversations.mockResolvedValue([]);
    client.createConversation.mockResolvedValue({ id: 'new-room', title: 'New conversation' });
    render(<ChatPage />);

    await waitFor(() => expect(client.createConversation).toHaveBeenCalledTimes(1));
    expect(await screen.findByTestId('message-input')).toBeInTheDocument();
  });
});
