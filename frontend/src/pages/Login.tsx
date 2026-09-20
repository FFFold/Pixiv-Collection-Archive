import { useState } from "react";
import { useNavigate } from "react-router-dom";

import { useLogin } from "../api/mutations";

export default function Login() {
  const [token, setToken] = useState("");
  const login = useLogin();
  const navigate = useNavigate();

  const submit = (event: React.FormEvent) => {
    event.preventDefault();
    login.mutate(token, {
      onSuccess: () => navigate("/", { replace: true }),
    });
  };

  return (
    <div className="flex h-full items-center justify-center bg-surface">
      <form
        onSubmit={submit}
        className="w-full max-w-sm rounded-xl border border-border-subtle bg-surface-raised p-6"
      >
        <h1 className="mb-1 text-lg font-semibold">Pixiv Archive</h1>
        <p className="mb-5 text-sm text-text-muted">输入访问令牌以继续</p>
        <input
          type="password"
          value={token}
          onChange={(event) => setToken(event.target.value)}
          placeholder="AUTH_TOKEN"
          autoFocus
          className="mb-3 w-full rounded-md border border-border-subtle bg-surface px-3 py-2 text-sm outline-none focus:border-accent"
        />
        <button
          type="submit"
          disabled={login.isPending || token.length === 0}
          className="w-full rounded-md bg-accent px-3 py-2 text-sm font-medium text-white disabled:opacity-50"
        >
          {login.isPending ? "登录中…" : "登录"}
        </button>
        {login.isError ? (
          <p className="mt-3 text-sm text-red-400">令牌无效或服务未配置 AUTH_TOKEN</p>
        ) : null}
      </form>
    </div>
  );
}
