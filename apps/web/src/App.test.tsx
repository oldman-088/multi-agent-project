import { describe, expect, it } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import App from './App';

describe('App shell i18n + direction (acceptance criteria 2)', () => {
  it('defaults to Arabic with dir=rtl on <html>', async () => {
    render(<App />);

    await waitFor(() => expect(document.documentElement.lang).toBe('ar'));
    expect(document.documentElement.dir).toBe('rtl');
    expect(screen.getByRole('heading', { name: 'مرحبًا بك في NEXUS' })).toBeInTheDocument();
    expect(screen.getByRole('navigation', { name: 'التنقل الرئيسي' })).toBeInTheDocument();
  });

  it('switching to English sets dir=ltr and shows the English UI', async () => {
    const user = userEvent.setup();
    render(<App />);

    await user.click(screen.getByRole('button', { name: 'English' }));

    await waitFor(() => expect(document.documentElement.lang).toBe('en'));
    expect(document.documentElement.dir).toBe('ltr');
    expect(await screen.findByRole('heading', { name: 'Welcome to NEXUS' })).toBeInTheDocument();
    expect(screen.getByRole('navigation', { name: 'Main navigation' })).toBeInTheDocument();
    expect(localStorage.getItem('nx.lang')).toBe('en');
  });

  it('switching to Persian sets dir=rtl and shows the Persian UI', async () => {
    const user = userEvent.setup();
    render(<App />);

    await user.click(screen.getByRole('button', { name: 'فارسی' }));

    await waitFor(() => expect(document.documentElement.lang).toBe('fa'));
    expect(document.documentElement.dir).toBe('rtl');
    expect(await screen.findByRole('heading', { name: 'به NEXUS خوش آمدید' })).toBeInTheDocument();
    expect(localStorage.getItem('nx.lang')).toBe('fa');
  });

  it('persists the language across reloads via localStorage', async () => {
    const user = userEvent.setup();
    render(<App />);

    await user.click(screen.getByRole('button', { name: 'English' }));
    await waitFor(() => expect(localStorage.getItem('nx.lang')).toBe('en'));

    // A fresh mount (as after a reload) reads nx.lang from storage.
    render(<App />);
    await waitFor(() => expect(document.documentElement.lang).toBe('en'));
    expect(document.documentElement.dir).toBe('ltr');
  });
});

describe('theme switching persists on <html> (SPEC 8.1)', () => {
  it('toggles data-theme between dark and light and stores it', async () => {
    const user = userEvent.setup();
    render(<App />);

    // Dark is the default operations theme.
    await waitFor(() => expect(document.documentElement.dataset.theme).toBe('dark'));

    await user.click(screen.getByRole('button', { name: 'الوضع النهاري' }));
    await waitFor(() => expect(document.documentElement.dataset.theme).toBe('light'));
    expect(localStorage.getItem('nx.theme')).toBe('light');

    await user.click(screen.getByRole('button', { name: 'الوضع الليلي' }));
    await waitFor(() => expect(document.documentElement.dataset.theme).toBe('dark'));
    expect(localStorage.getItem('nx.theme')).toBe('dark');
  });
});
