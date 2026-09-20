import { useLogout } from "../api/mutations";

export default function Settings() {
  const logout = useLogout();

  return (
    <div className="max-w-xl space-y-5 p-6">
      <h1 className="text-base font-semibold">设置</h1>

      <div className="rounded-lg border border-border-subtle bg-surface-raised p-4 text-sm">
        <div className="mb-2 font-medium">认证</div>
        <p className="mb-3 text-text-muted">
          当前使用单用户令牌认证。退出后需要重新输入 AUTH_TOKEN 登录。
        </p>
        <button
          type="button"
          onClick={() => logout.mutate()}
          disabled={logout.isPending}
          className="rounded-md border border-border-subtle px-3 py-1.5 hover:border-red-400 hover:text-red-300"
        >
          退出登录
        </button>
      </div>

      <div className="rounded-lg border border-border-subtle bg-surface-raised p-4 text-sm">
        <div className="mb-2 font-medium">服务配置</div>
        <p className="text-text-muted">
          同步间隔、代理、图片镜像、并发等通过环境变量配置，修改后需重启服务。
          详见仓库 README 的配置表。
        </p>
      </div>

      <div className="rounded-lg border border-border-subtle bg-surface-raised p-4 text-sm">
        <div className="mb-2 font-medium">接口文档</div>
        <a className="underline" href="/docs" target="_blank" rel="noreferrer">
          /docs（OpenAPI）
        </a>
      </div>
    </div>
  );
}
