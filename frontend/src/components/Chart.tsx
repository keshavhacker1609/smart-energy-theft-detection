import type { EChartsOption } from "echarts";
import ReactEChartsCore from "echarts-for-react/lib/core";
import type { CSSProperties, Ref } from "react";
import { echarts } from "@/lib/charts/echarts";

interface ChartProps {
  option: EChartsOption;
  style?: CSSProperties;
  ariaLabel?: string;
  ref?: Ref<ReactEChartsCore>;
}

export function Chart({ option, style, ariaLabel, ref }: ChartProps) {
  return (
    <div role="img" aria-label={ariaLabel}>
      <ReactEChartsCore
        ref={ref}
        echarts={echarts}
        option={option}
        notMerge
        style={{ width: "100%", ...style }}
        opts={{ renderer: "canvas" }}
      />
    </div>
  );
}
