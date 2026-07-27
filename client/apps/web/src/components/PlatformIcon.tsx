import type { Platform } from "@oral/types";

import douyinSvg from "../assets/platforms/douyin.svg?raw";
import kuaishouSvg from "../assets/platforms/kuaishou.svg?raw";
import shipinhaoSvg from "../assets/platforms/shipinhao.svg?raw";
import xiaohongshuSvg from "../assets/platforms/xiaohongshu.svg?raw";

/** 四平台官方品牌 SVG（来源：svglogo.top 收录的官方矢量） */
const SVGS: Record<Platform, string> = {
  douyin: douyinSvg,
  kuaishou: kuaishouSvg,
  xiaohongshu: xiaohongshuSvg,
  shipinhao: shipinhaoSvg,
};

/**
 * 平台品牌图标：内联官方 SVG，随 size 等比缩放。
 * 抖音图标自带黑色圆角底，深色主题下加细描边区分边界。
 */
export default function PlatformIcon({
  platform,
  size = 20,
}: {
  platform: Platform;
  size?: number;
}) {
  return (
    <span
      role="img"
      aria-label={platform}
      className={`inline-flex shrink-0 items-center justify-center overflow-hidden rounded-md align-middle [&_svg]:h-full [&_svg]:w-full ${
        platform === "douyin" ? "ring-1 ring-white/15" : ""
      }`}
      style={{ width: size, height: size }}
      // 素材来自可信官方矢量，构建期内联
      dangerouslySetInnerHTML={{ __html: SVGS[platform] }}
    />
  );
}
