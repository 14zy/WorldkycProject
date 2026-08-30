import { useEffect, useState } from "react";

type TelegramUser = {
  id: number;
  username?: string | null;
  firstName?: string | null;
  lastName?: string | null;
  languageCode?: string | null;
};

type BootstrapPayload = {
  telegramUser: TelegramUser;
  linked: boolean;
};

type LoginPayload = {
  linked: boolean;
  telegramUser: TelegramUser;
  user?: {
    userName?: string | null;
    organizationName?: string | null;
    emailAddress?: string | null;
  };
};

type LogoutPayload = {
  linked: boolean;
  telegramUser: TelegramUser;
};

type ConnectionCodePayload = {
  connectUrl: string;
  expiresAt: string;
};

type VLinkItem = {
  id: string;
  reference: string;
  name: string;
  status: string;
  url: string;
};

type AsyncState = "idle" | "loading" | "success" | "error";

class ApiError extends Error {
  code?: string;

  constructor(message: string, code?: string) {
    super(message);
    this.code = code;
  }
}

function getTelegramWebApp() {
  return window.Telegram?.WebApp;
}

async function readJson<T>(response: Response): Promise<T> {
  const payload = await response.json().catch(() => ({}));
  if (!response.ok) {
    const errorMessage =
      typeof payload?.error === "string" ? payload.error : "Request failed";
    const details = typeof payload?.details === "string" ? payload.details : "";
    const code = typeof payload?.code === "string" ? payload.code : undefined;
    throw new ApiError(details ? `${errorMessage}: ${details}` : errorMessage, code);
  }
  return payload as T;
}

function formatTelegramName(user: TelegramUser | null) {
  if (!user) {
    return "Telegram user";
  }
  const fullName = [user.firstName, user.lastName].filter(Boolean).join(" ").trim();
  if (fullName) {
    return fullName;
  }
  if (user.username) {
    return `@${user.username}`;
  }
  return `User #${user.id}`;
}

function getStatusChipClassName(status: string) {
  switch (status.trim().toLowerCase()) {
    case "active":
      return "status-chip status-chip--active";
    case "expired":
      return "status-chip status-chip--expired";
    default:
      return "status-chip status-chip--neutral";
  }
}

export function App() {
  const [initData, setInitData] = useState("");
  const [bootstrapState, setBootstrapState] = useState<AsyncState>("loading");
  const [bootstrapError, setBootstrapError] = useState("");
  const [telegramUser, setTelegramUser] = useState<TelegramUser | null>(null);
  const [linked, setLinked] = useState(false);
  const [loginSummary, setLoginSummary] = useState<LoginPayload["user"] | null>(null);
  const [connectState, setConnectState] = useState<AsyncState>("idle");
  const [connectError, setConnectError] = useState("");
  const [logoutState, setLogoutState] = useState<AsyncState>("idle");
  const [logoutError, setLogoutError] = useState("");
  const [logoutChipArmed, setLogoutChipArmed] = useState(false);
  const [vlinks, setVlinks] = useState<VLinkItem[]>([]);
  const [vlinksState, setVlinksState] = useState<AsyncState>("idle");
  const [vlinksError, setVlinksError] = useState("");
  const [copyNotice, setCopyNotice] = useState("");

  useEffect(() => {
    const tg = getTelegramWebApp();
    if (!tg) {
      setBootstrapState("error");
      setBootstrapError("Open this Mini App inside Telegram.");
      return;
    }

    tg.ready();
    tg.expand();
    tg.setHeaderColor?.("#13261b");
    tg.setBackgroundColor?.("#f6f2e8");

    if (!tg.initData) {
      setBootstrapState("error");
      setBootstrapError("Telegram initData was not provided.");
      return;
    }

    setInitData(tg.initData);

    const run = async () => {
      try {
        const payload = await fetch("/api/tma/bootstrap", {
          method: "POST",
          headers: {
            "Content-Type": "application/json",
          },
          body: JSON.stringify({ initData: tg.initData }),
        }).then(readJson<BootstrapPayload>);

        setTelegramUser(payload.telegramUser);
        setLinked(payload.linked);
        setBootstrapState("success");
      } catch (error) {
        setBootstrapState("error");
        setBootstrapError(error instanceof Error ? error.message : "Bootstrap failed.");
      }
    };

    void run();
  }, []);

  useEffect(() => {
    if (!linked || !initData) {
      return;
    }

    const run = async () => {
      setVlinksState("loading");
      setVlinksError("");
      try {
        const payload = await fetch("/api/tma/vlinks", {
          headers: {
            "X-Telegram-Init-Data": initData,
          },
        }).then(readJson<{ items: VLinkItem[] }>);
        setVlinks(payload.items);
        setVlinksState("success");
      } catch (error) {
        if (error instanceof ApiError && error.code === "AUTH_SESSION_EXPIRED") {
          setLinked(false);
          setLoginSummary(null);
          setVlinks([]);
          setVlinksState("idle");
          setVlinksError("");
          setConnectError("Your account link is no longer active. Connect it again.");
          return;
        }
        setVlinksState("error");
        setVlinksError(error instanceof Error ? error.message : "Failed to load vlinks.");
      }
    };

    void run();
  }, [initData, linked]);

  useEffect(() => {
    if (!copyNotice) {
      return;
    }
    const timer = window.setTimeout(() => setCopyNotice(""), 1800);
    return () => window.clearTimeout(timer);
  }, [copyNotice]);

  async function handleConnect() {
    if (!initData) {
      return;
    }

    setConnectState("loading");
    setConnectError("");

    try {
      const payload = await fetch("/api/tma/connect/code", {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
        },
        body: JSON.stringify({ initData }),
      }).then(readJson<ConnectionCodePayload>);

      setConnectState("success");
      const tg = getTelegramWebApp();
      if (tg?.openLink) {
        tg.openLink(payload.connectUrl);
      } else {
        window.location.assign(payload.connectUrl);
      }
    } catch (error) {
      setConnectState("error");
      setConnectError(error instanceof Error ? error.message : "Unable to start connection.");
    }
  }

  async function handleLogout() {
    if (!initData || logoutState === "loading") {
      return;
    }

    const confirmed = window.confirm(
      "Log out and unlink this Telegram account from WorldKyc? Inline access will stop until you sign in again.",
    );
    if (!confirmed) {
      return;
    }

    setLogoutState("loading");
    setLogoutError("");
    setLogoutChipArmed(false);

    try {
      const payload = await fetch("/api/tma/logout", {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
        },
        body: JSON.stringify({ initData }),
      }).then(readJson<LogoutPayload>);

      setLinked(payload.linked);
      setTelegramUser(payload.telegramUser);
      setConnectError("");
      setConnectState("idle");
      setLoginSummary(null);
      setVlinks([]);
      setVlinksState("idle");
      setVlinksError("");
      setCopyNotice("");
      setLogoutChipArmed(false);
      setLogoutState("success");
    } catch (error) {
      setLogoutState("error");
      setLogoutError(error instanceof Error ? error.message : "Logout failed.");
    }
  }

  function toggleLogoutChip() {
    if (logoutState === "loading") {
      return;
    }
    setLogoutChipArmed((armed) => !armed);
  }

  async function handleCopy(value: string) {
    try {
      await navigator.clipboard.writeText(value);
      setCopyNotice("Copied");
    } catch {
      setCopyNotice("Copy failed");
    }
  }

  const isNotTelegram =
    bootstrapState === "error" && bootstrapError === "Open this Mini App inside Telegram.";

  return (
    <main className="shell">
      {bootstrapState === "loading" ? (
        <section className="panel panel--loading">
          <div className="spinner" />
          <div>
            <h2>Launching...</h2>
            <p>Validating Telegram session and loading your current link state.</p>
          </div>
        </section>
      ) : null}

      {bootstrapState === "error" ? (
        <section className="panel panel--error">
          <h2>{isNotTelegram ? "Open inside Telegram" : "Mini App is unavailable"}</h2>
          <p>{bootstrapError}</p>
        </section>
      ) : null}

      {bootstrapState === "success" && !linked ? (
        <section className="panel">
          <div className="panel__header">
            <div>
              <div className="eyebrow">TONStealthID Login</div>
              <h2>Link your account</h2>
            </div>
            <span className="status-chip">
              {telegramUser ? formatTelegramName(telegramUser) : "Telegram user"}
            </span>
          </div>
          <p>Continue to WorldKYC to connect this Telegram account. Your password stays on WorldKYC.</p>
          <button
            type="button"
            onClick={() => void handleConnect()}
            disabled={connectState === "loading"}
          >
            {connectState === "loading" ? "Preparing connection..." : "Continue to WorldKYC"}
          </button>
          {connectState === "success" ? (
            <p className="feedback">Complete the connection in the WorldKYC page, then reopen this Mini App.</p>
          ) : null}
          {connectError ? <p className="feedback feedback--error">{connectError}</p> : null}
        </section>
      ) : null}

      {bootstrapState === "success" && linked ? (
        <>
          <section className="panel panel--accent">
            <div className="panel__header">
              <div>
                <div className="eyebrow">Account Status</div>
                <h2 className="account-status-title">Linked&nbsp;and&nbsp;ready</h2>
              </div>
              {logoutChipArmed ? (
                <button
                  type="button"
                  className="status-chip status-chip-button status-chip-button--danger"
                  aria-expanded={true}
                  aria-haspopup="dialog"
                  onClick={() => void handleLogout()}
                  disabled={logoutState === "loading"}
                >
                  {logoutState === "loading" ? "Logging out..." : "Log out"}
                </button>
              ) : (
                <button
                  type="button"
                  className="status-chip status-chip--success status-chip-button"
                  aria-expanded={false}
                  aria-haspopup="dialog"
                  onClick={toggleLogoutChip}
                  disabled={logoutState === "loading"}
                >
                  Connected
                </button>
              )}
            </div>
            <p>
              {loginSummary?.organizationName
                ? `Account: ${loginSummary.organizationName} is now linked to Telegram: ${formatTelegramName(telegramUser)}.`
                : `Your Telegram account is linked. Inline mode uses your synchronized WorldKYC VLinks.`}
            </p>
            {loginSummary?.emailAddress ? (
              <p className="meta-line">Main E-mail: {loginSummary.emailAddress}</p>
            ) : null}
            {logoutError ? <p className="feedback feedback--error">{logoutError}</p> : null}
          </section>

          <section className="panel">
            <div className="panel__header">
              <div>
                <div className="eyebrow">VLinks</div>
                <h2>Your Anonymous E-mails</h2>
              </div>
              {copyNotice ? <span className="status-chip">{copyNotice}</span> : null}
            </div>

            {vlinksState === "loading" ? (
              <div className="inline-state">Loading verified links...</div>
            ) : null}
            {vlinksState === "error" ? (
              <div className="feedback feedback--error">{vlinksError}</div>
            ) : null}
            {vlinksState === "success" && vlinks.length === 0 ? (
              <div className="inline-state">
                No verified links were returned for this account.
              </div>
            ) : null}
            {vlinksState === "success" && vlinks.length > 0 ? (
              <div className="vlink-list">
                {vlinks.map((item) => (
                  <article className="vlink-card" key={item.id} style={{ width: "auto" }}>
                    <div className="vlink-card__header">
                      <div className="vlink-card__title">
                        <h3>{item.name}</h3>
                        <div className="vlink-card__meta">
                          <span className="status-chip vlink-reference-chip">{item.reference}</span>
                          <span className={getStatusChipClassName(item.status)}>{item.status}</span>
                        </div>
                      </div>
                    </div>
                    <a className="vlink-url" href={item.url} target="_blank" rel="noreferrer">
                      {item.url}
                    </a>
                    <a className="vlink-email" href={`mailto:${item.reference}@tonstealthid.com`} target="_blank" rel="noreferrer">
                      {`${item.reference}@tonstealthid.com`}
                    </a>
                    <div className="vlink-actions">
                      <a href={item.url} target="_blank" rel="noreferrer">
                        Open
                      </a>
                      <button type="button" onClick={() => void handleCopy(item.url)}>
                        Copy
                      </button>
                    </div>
                  </article>
                ))}
              </div>
            ) : null}
          </section>
        </>
      ) : null}
    </main>
  );
}
