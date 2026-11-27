import { useState, type FormEvent, type KeyboardEvent } from 'react';
import { useTranslation } from 'react-i18next';
import { Send } from 'lucide-react';
import { Button } from '../../../components/ui/button';

interface ChatComposerProps {
  disabled: boolean;
  sending: boolean;
  onSend: (content: string) => void;
}

/** Message composer: multi-line input, Enter sends (Shift+Enter new line). */
export function ChatComposer({ disabled, sending, onSend }: ChatComposerProps) {
  const { t } = useTranslation();
  const [value, setValue] = useState('');

  function submit() {
    const content = value.trim();
    if (!content || disabled || sending) {
      return;
    }
    setValue('');
    onSend(content);
  }

  function handleSubmit(event: FormEvent) {
    event.preventDefault();
    submit();
  }

  function handleKeyDown(event: KeyboardEvent<HTMLTextAreaElement>) {
    if (event.key === 'Enter' && !event.shiftKey) {
      event.preventDefault();
      submit();
    }
  }

  return (
    <form onSubmit={handleSubmit} className="flex items-end gap-2">
      <label htmlFor="message-input" className="sr-only">
        {t('chat.composerLabel')}
      </label>
      <textarea
        id="message-input"
        data-testid="message-input"
        rows={2}
        value={value}
        disabled={disabled || sending}
        onChange={(event) => setValue(event.target.value)}
        onKeyDown={handleKeyDown}
        placeholder={t('chat.composerPlaceholder')}
        className="flex-1 rounded-nx-md border border-nx-border bg-nx-surface px-3 py-2 text-sm text-nx-fg focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-nx-focus disabled:opacity-50"
      />
      <Button
        type="submit"
        data-testid="send-button"
        disabled={disabled || sending || value.trim().length === 0}
      >
        <Send className="h-4 w-4" aria-hidden="true" />
        {t('chat.send')}
      </Button>
    </form>
  );
}
