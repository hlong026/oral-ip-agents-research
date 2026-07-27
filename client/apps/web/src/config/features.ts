export const IM_ENABLED = import.meta.env.VITE_IM_ENABLED === "true";

// V1.1 占位页特性开关（默认关闭）：未开启时侧边栏隐藏入口、直达路由重定向工作台，
// 避免生产环境用户把演示数据误判为自己的真实数据。
export const ANALYTICS_PREVIEW =
  import.meta.env.VITE_ANALYTICS_PREVIEW === "true";
export const ASSETS_PREVIEW = import.meta.env.VITE_ASSETS_PREVIEW === "true";
