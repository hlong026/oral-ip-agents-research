import { BarChart, LineChart } from "echarts/charts";
import {
  GridComponent,
  LegendComponent,
  TooltipComponent,
} from "echarts/components";
import * as echarts from "echarts/core";
import { SVGRenderer } from "echarts/renderers";
import { useEffect, useRef } from "react";

// 按需注册：总览只用折线/柱状 + 网格/提示/图例，SVG 渲染在暗色玻璃上更锐利
echarts.use([
  LineChart,
  BarChart,
  GridComponent,
  TooltipComponent,
  LegendComponent,
  SVGRenderer,
]);

export type ChartOption = echarts.EChartsCoreOption;

interface DashboardChartProps {
  option: ChartOption;
  height?: number;
  ariaLabel: string;
}

export default function DashboardChart({
  option,
  height = 240,
  ariaLabel,
}: DashboardChartProps) {
  const containerRef = useRef<HTMLDivElement>(null);
  const chartRef = useRef<echarts.ECharts | null>(null);

  useEffect(() => {
    if (!containerRef.current) return;
    const chart = echarts.init(containerRef.current, undefined, {
      renderer: "svg",
    });
    chartRef.current = chart;
    // jsdom 无 ResizeObserver，测试环境下跳过自适应
    const observer =
      typeof ResizeObserver !== "undefined"
        ? new ResizeObserver(() => chart.resize())
        : null;
    observer?.observe(containerRef.current);
    return () => {
      observer?.disconnect();
      chart.dispose();
      chartRef.current = null;
    };
  }, []);

  useEffect(() => {
    chartRef.current?.setOption(option, true);
  }, [option]);

  return (
    <div
      ref={containerRef}
      style={{ height }}
      role="img"
      aria-label={ariaLabel}
    />
  );
}
