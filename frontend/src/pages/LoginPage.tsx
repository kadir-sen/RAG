import { useEffect, useState } from 'react';
import { useLocation, useNavigate } from 'react-router-dom';
import { useAuthStore } from '../stores/authStore';

type LocationState = { from?: { pathname?: string } } | null;

export default function LoginPage() {
  const navigate = useNavigate();
  const location = useLocation();
  const token = useAuthStore((s) => s.token);
  const status = useAuthStore((s) => s.status);
  const error = useAuthStore((s) => s.error);
  const login = useAuthStore((s) => s.login);

  const [username, setUsername] = useState('');
  const [password, setPassword] = useState('');

  const redirectTo = (location.state as LocationState)?.from?.pathname || '/projects';

  useEffect(() => {
    if (token) {
      navigate(redirectTo, { replace: true });
    }
  }, [token, navigate, redirectTo]);

  const handleSubmit = async (event: React.FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (!username.trim() || !password) return;
    try {
      await login(username.trim(), password);
    } catch {
      // error surfaced via store.error
    }
  };

  const loading = status === 'loading';

  return (
    <div className="min-h-screen w-full relative welcome-blueprint flex items-center justify-center px-5 bg-[var(--bg-primary)]">
      <div className="absolute top-5 left-5 font-mono text-[10px] tracking-[0.18em] uppercase text-[var(--text-muted)]">
        [ COAIR · ACCESS ]
      </div>
      <div className="absolute bottom-5 right-5 font-mono text-[10px] tracking-[0.18em] uppercase text-[var(--text-muted)]">
        [ CONSTRUCTION · INTELLIGENCE ]
      </div>

      <div className="w-full max-w-md animate-fade-in-up">
        <div className="flex items-center gap-4 mb-7">
          <div
            className="w-14 h-14 grid place-items-center border border-[var(--border)] bg-[var(--wash)] rounded"
            aria-hidden="true"
          >
            <span className="font-mono font-bold text-[var(--text-primary)] tracking-wider text-lg">CO</span>
          </div>
          <div>
            <h1 className="text-2xl md:text-3xl font-semibold tracking-tight text-[var(--text-primary)]">
              <span>CO</span>
              <span className="text-[var(--brand)]">Air</span>
            </h1>
            <p className="text-xs md:text-sm text-[var(--text-secondary)] font-mono mt-1 tracking-wide">
              sign in to continue
            </p>
          </div>
        </div>

        <form
          onSubmit={handleSubmit}
          className="bg-[var(--wash)] border border-[var(--border)] rounded-md overflow-hidden"
        >
          <div className="flex items-center gap-2 px-4 pt-4">
            <span className="font-mono text-[10px] tracking-[0.18em] px-1.5 py-0.5 border border-[var(--border)] text-[var(--text-secondary)] rounded">
              ACCESS · 01
            </span>
            <span className="font-mono text-[11px] text-[var(--text-muted)] tracking-wide">
              credentials
            </span>
          </div>

          <div className="px-4 pt-4 pb-2">
            <label
              htmlFor="login-username"
              className="block font-mono text-[10px] tracking-[0.16em] uppercase text-[var(--text-secondary)] mb-1.5"
            >
              Username
            </label>
            <input
              id="login-username"
              autoFocus
              autoComplete="username"
              value={username}
              onChange={(e) => setUsername(e.target.value)}
              disabled={loading}
              className="w-full bg-[var(--bg-primary)] border border-[var(--border)] rounded px-3 py-2 font-mono text-sm text-[var(--text-primary)] outline-none focus:border-[var(--accent)] transition-colors"
            />
          </div>

          <div className="px-4 pt-3 pb-4">
            <label
              htmlFor="login-password"
              className="block font-mono text-[10px] tracking-[0.16em] uppercase text-[var(--text-secondary)] mb-1.5"
            >
              Password
            </label>
            <input
              id="login-password"
              type="password"
              autoComplete="current-password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              disabled={loading}
              className="w-full bg-[var(--bg-primary)] border border-[var(--border)] rounded px-3 py-2 font-mono text-sm text-[var(--text-primary)] outline-none focus:border-[var(--accent)] transition-colors"
            />
          </div>

          {error && (
            <div className="mx-4 mb-4 px-3 py-2 rounded border border-[var(--danger)] bg-[var(--wash)]">
              <span className="font-mono text-[10px] tracking-[0.16em] text-[var(--danger)]">
                [ ERROR · {error === 'invalid_credentials' ? '401' : 'AUTH'} ]
              </span>
              <p className="font-mono text-[11px] text-[var(--text-secondary)] mt-1">
                {error === 'invalid_credentials'
                  ? 'Wrong username or password.'
                  : error === 'account_disabled'
                    ? 'This account is disabled. Contact an administrator.'
                    : 'Could not sign you in. Please try again.'}
              </p>
            </div>
          )}

          <button
            type="submit"
            disabled={loading || !username.trim() || !password}
            className="w-full px-4 py-3 bg-[var(--accent)] hover:bg-[var(--accent-hover)] disabled:bg-[var(--wash-firm)] disabled:text-[var(--text-muted)] text-[var(--accent-ink)] font-mono text-xs tracking-[0.18em] uppercase transition-colors"
          >
            {loading ? '· Authenticating ·' : 'Enter →'}
          </button>
        </form>

        <p className="font-mono text-[10px] tracking-[0.14em] text-[var(--text-muted)] text-center mt-6">
          accounts are provisioned by your administrator.
        </p>
      </div>
    </div>
  );
}
