import { describe, expect, it } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import App from '../../App';

async function openPalette(user: ReturnType<typeof userEvent.setup>) {
  await user.keyboard('{Control>}k{/Control}');
  return await screen.findByRole('dialog');
}

describe('command palette (SPEC 8.3-J)', () => {
  it('opens with Ctrl+K and focuses the combobox', async () => {
    const user = userEvent.setup();
    render(<App />);

    const dialog = await openPalette(user);
    expect(dialog).toBeInTheDocument();

    const combobox = screen.getByRole('combobox');
    await waitFor(() => expect(combobox).toHaveFocus());
    expect(combobox).toHaveAttribute('aria-expanded', 'true');
    expect(combobox).toHaveAttribute('aria-controls', 'command-palette-listbox');
  });

  it('lists exactly the 4 structural commands in Arabic by default', async () => {
    const user = userEvent.setup();
    render(<App />);

    await openPalette(user);
    const options = screen.getAllByRole('option');
    expect(options).toHaveLength(4);
    expect(options[0]).toHaveTextContent('الانتقال إلى الصفحة الرئيسية');
    expect(options[1]).toHaveTextContent('تبديل المظهر');
    expect(options[2]).toHaveTextContent('تغيير اللغة إلى الإنجليزية');
    expect(options[3]).toHaveTextContent('تغيير اللغة إلى الفارسية');
    // The current language is never offered as a switch target.
    expect(screen.queryByRole('option', { name: /العربية/ })).not.toBeInTheDocument();
  });

  it('filters commands by label and keyword', async () => {
    const user = userEvent.setup();
    render(<App />);

    await openPalette(user);
    const combobox = screen.getByRole('combobox');

    await user.type(combobox, 'المظهر');
    expect(screen.getAllByRole('option')).toHaveLength(1);
    expect(screen.getByRole('option')).toHaveTextContent('تبديل المظهر');

    await user.clear(combobox);
    await user.type(combobox, 'zzz-no-such-command');
    expect(screen.queryAllByRole('option')).toHaveLength(0);
    expect(screen.getByText('لا توجد أوامر مطابقة')).toBeInTheDocument();
  });

  it('Enter runs the active command — toggling the theme', async () => {
    const user = userEvent.setup();
    render(<App />);
    await waitFor(() => expect(document.documentElement.dataset.theme).toBe('dark'));

    await openPalette(user);
    await user.keyboard('{ArrowDown}'); // active = toggle-theme
    await user.keyboard('{Enter}');

    await waitFor(() => expect(document.documentElement.dataset.theme).toBe('light'));
    expect(localStorage.getItem('nx.theme')).toBe('light');
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
  });

  it('Enter on a language command switches the UI language', async () => {
    const user = userEvent.setup();
    render(<App />);

    await openPalette(user);
    await user.keyboard('en'); // keyword of set-language-en
    expect(screen.getAllByRole('option')).toHaveLength(1);
    expect(screen.getByRole('option')).toHaveTextContent('تغيير اللغة إلى الإنجليزية');
    await user.keyboard('{Enter}');

    await waitFor(() => expect(document.documentElement.lang).toBe('en'));
    expect(document.documentElement.dir).toBe('ltr');
    expect(await screen.findByRole('heading', { name: 'Welcome to NEXUS' })).toBeInTheDocument();
  });

  it('Escape closes the palette', async () => {
    const user = userEvent.setup();
    render(<App />);

    await openPalette(user);
    await user.keyboard('{Escape}');
    await waitFor(() => expect(screen.queryByRole('dialog')).not.toBeInTheDocument());
  });

  it('the header button opens the palette too', async () => {
    const user = userEvent.setup();
    render(<App />);

    // The header trigger and the home-screen hint share this accessible name;
    // the header renders first in DOM order.
    const triggers = screen.getAllByRole('button', { name: 'فتح لوحة الأوامر' });
    expect(triggers.length).toBeGreaterThanOrEqual(1);
    await user.click(triggers[0]!);
    expect(await screen.findByRole('dialog')).toBeInTheDocument();
    expect(screen.getByRole('combobox')).toBeInTheDocument();
  });
});
