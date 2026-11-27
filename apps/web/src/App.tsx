import { BrowserRouter, Navigate, Route, Routes } from 'react-router-dom';
import { CommandPalette } from './features/command-palette/CommandPalette';
import { CommandPaletteProvider } from './features/command-palette/CommandPaletteProvider';
import { HomeScreen } from './features/home/HomeScreen';
import { AppShell } from './features/shell/AppShell';
import { ThemeProvider } from './features/theme/ThemeProvider';

/**
 * App root: providers and routing only (Section 8.4 — no god components).
 * i18n is initialized in src/i18n before render (see main.tsx).
 */
export default function App() {
  return (
    <ThemeProvider>
      <CommandPaletteProvider>
        <BrowserRouter>
          <Routes>
            <Route element={<AppShell />}>
              <Route path="/" element={<HomeScreen />} />
              <Route path="*" element={<Navigate to="/" replace />} />
            </Route>
          </Routes>
          {/* Uses useNavigate, so it must render inside the router. */}
          <CommandPalette />
        </BrowserRouter>
      </CommandPaletteProvider>
    </ThemeProvider>
  );
}
