import type { TeamHostedContext } from "../api/client";

type CaptchaApi = {
  render: (container: HTMLElement, options: Record<string, unknown>) => string;
  execute: (widget: string, options: Record<string, unknown>) => Promise<{ response: string }>;
  remove: (widget: string) => void;
};

declare global { interface Window { hcaptcha?: CaptchaApi } }
let loading: Promise<void> | null = null;
function load(): Promise<void> {
  if (window.hcaptcha) return Promise.resolve();
  if (loading) return loading;
  loading = new Promise<void>((resolve, reject) => {
    const script = document.createElement("script");
    script.src = "https://js.hcaptcha.com/1/api.js?render=explicit";
    script.async = true;
    const timer = window.setTimeout(() => reject(new Error("验证组件加载超时，请打开官方结账页完成验证")), 20000);
    script.onload = () => { window.clearTimeout(timer); window.hcaptcha ? resolve() : reject(new Error("验证组件未就绪")); };
    script.onerror = () => { window.clearTimeout(timer); script.remove(); reject(new Error("验证组件加载失败，请打开官方结账页完成验证")); };
    document.head.appendChild(script);
  }).catch((err) => { loading = null; throw err; });
  return loading;
}

/** Use the live provider widget; no captured tokens, solvers or invented values. */
export async function hostedCaptcha(context: TeamHostedContext): Promise<string> {
  const config = context.passive_captcha;
  if (!config?.site_key) return "";
  await load();
  const api = window.hcaptcha!;
  const container = document.createElement("div");
  document.body.appendChild(container);
  let widget: string | undefined;
  let timer: ReturnType<typeof setTimeout> | undefined;
  try {
    widget = api.render(container, { sitekey: config.site_key, size: "invisible" });
    const request: Record<string, unknown> = { async: true };
    if (config.rqdata) request.rqdata = config.rqdata;
    const result = await Promise.race([
      api.execute(widget, request),
      new Promise<never>((_, reject) => { timer = setTimeout(() => reject(new Error("验证超时，请打开官方结账页完成验证")), 120000); }),
    ]);
    if (!result?.response) throw new Error("Stripe 验证未返回令牌，请打开官方结账页完成验证");
    return result.response;
  } finally {
    clearTimeout(timer);
    if (widget !== undefined) api.remove(widget);
    container.remove();
  }
}
