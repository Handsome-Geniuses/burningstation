"use client";

import {
    type CSSProperties,
    type ReactNode,
    useLayoutEffect,
    useMemo,
    useRef,
    useState,
} from "react";

type ToothedFrameOrientation = "horizontal" | "vertical" | "auto";
export type ToothedFrameDirection = "cw" | "ccw" | "off";

type ToothedFrameProps = {
    children?: ReactNode;

    /**
     * Optional explicit inner size.
     * If omitted, children are measured and drive the inner size.
     */
    innerWidth?: number;
    innerHeight?: number;

    minInnerWidth?: number;
    minInnerHeight?: number;

    contentPaddingX?: number;
    contentPaddingY?: number;

    orientation?: ToothedFrameOrientation;
    direction?: ToothedFrameDirection;

    minStraightLength?: number;

    /**
     * Total visual distance from the inner pill edge to the outer body edge.
     *
     * This is respected exactly.
     * It is allowed to be smaller than teethThickness.
     */
    outerThickness?: number;

    /**
     * Empty space between the inner pill and the inner edge of the teeth.
     */
    toothSpacingFromInner?: number;

    /**
     * Thickness of the moving tooth stroke.
     */
    teethThickness?: number;

    toothWidth?: number;
    toothGap?: number;

    /**
     * Duration in seconds for one tooth-pitch movement.
     *
     * Smaller = faster.
     * 0 = no animation.
     */
    toothSpeed?: number;

    outerBorderWidth?: number;

    outerFill?: string;
    outerStroke?: string;
    teethFill?: string;
    innerFill?: string;

    className?: string;
    contentClassName?: string;
    style?: CSSProperties;
};

type Size = {
    width: number;
    height: number;
};

function ToothedFrame({
    children,

    innerWidth,
    innerHeight,

    minInnerWidth = 10,
    minInnerHeight = 2,

    contentPaddingX = 0,
    contentPaddingY = 0,

    orientation = "auto",
    direction = "off",

    minStraightLength = 1,

    outerThickness = 36,

    toothSpacingFromInner = 8,
    teethThickness = 20,

    toothWidth = 14,
    toothGap = 7,
    toothSpeed = 0.35,

    outerBorderWidth = 4,

    outerFill = "#18181b",
    outerStroke = "#3f3f46",
    teethFill = "#71717a",
    innerFill = "#71717a",

    className = "",
    contentClassName = "",
    style,
}: ToothedFrameProps) {
    const contentRef = useRef<HTMLDivElement | null>(null);

    const [contentSize, setContentSize] = useState<Size>({
        width: 0,
        height: 0,
    });

    useLayoutEffect(() => {
        const element = contentRef.current;

        if (!element) return;

        const observer = new ResizeObserver((entries) => {
            const entry = entries[0];

            if (!entry) return;

            const { width, height } = entry.contentRect;

            setContentSize({
                width: Math.ceil(width),
                height: Math.ceil(height),
            });
        });

        observer.observe(element);

        return () => {
            observer.disconnect();
        };
    }, []);

    const geometry = useMemo(() => {
        const toothPitch = toothWidth + toothGap;

        /**
         * The teeth may extend farther from the inner pill than the visual outer body.
         *
         * outerThickness controls the dark outer body.
         * canvasThickness controls the invisible SVG size so teeth do not get clipped.
         */
        const toothOuterReachFromInner =
            toothSpacingFromInner + teethThickness;

        const canvasThickness = Math.max(
            outerThickness,
            toothOuterReachFromInner
        );

        const measuredInnerWidth =
            contentSize.width + contentPaddingX * 2;

        const measuredInnerHeight =
            contentSize.height + contentPaddingY * 2;

        const resolvedInnerWidth = Math.max(
            innerWidth ?? measuredInnerWidth,
            minInnerWidth
        );

        const resolvedInnerHeight = Math.max(
            innerHeight ?? measuredInnerHeight,
            minInnerHeight
        );

        const resolvedOrientation: Exclude<
            ToothedFrameOrientation,
            "auto"
        > =
            orientation === "auto"
                ? resolvedInnerWidth >= resolvedInnerHeight
                    ? "horizontal"
                    : "vertical"
                : orientation;

        const extraWidth =
            resolvedOrientation === "horizontal"
                ? Math.max(
                    0,
                    resolvedInnerHeight +
                    minStraightLength -
                    resolvedInnerWidth
                )
                : 0;

        const extraHeight =
            resolvedOrientation === "vertical"
                ? Math.max(
                    0,
                    resolvedInnerWidth +
                    minStraightLength -
                    resolvedInnerHeight
                )
                : 0;

        const width =
            resolvedInnerWidth + canvasThickness * 2 + extraWidth;

        const height =
            resolvedInnerHeight + canvasThickness * 2 + extraHeight;

        const innerX = canvasThickness + extraWidth / 2;
        const innerY = canvasThickness + extraHeight / 2;

        /**
         * Outer body respects outerThickness exactly.
         * It can be smaller than the teeth.
         */
        const outerX = canvasThickness - outerThickness;
        const outerY = canvasThickness - outerThickness;

        const outerWidth =
            resolvedInnerWidth + outerThickness * 2 + extraWidth;

        const outerHeight =
            resolvedInnerHeight + outerThickness * 2 + extraHeight;

        /**
         * SVG stroke is centered on the path.
         * So the path center needs to be:
         * toothSpacingFromInner + half the teeth thickness
         * away from the inner pill.
         */
        const toothCenterOffsetFromInner =
            toothSpacingFromInner + teethThickness / 2;

        const beltX =
            innerX - toothCenterOffsetFromInner - extraWidth / 2;

        const beltY =
            innerY - toothCenterOffsetFromInner - extraHeight / 2;

        const beltWidth =
            resolvedInnerWidth +
            toothCenterOffsetFromInner * 2 +
            extraWidth;

        const beltHeight =
            resolvedInnerHeight +
            toothCenterOffsetFromInner * 2 +
            extraHeight;

        let teethPath = "";
        let teethRadius = 0;
        let straightLength = 0;

        if (resolvedOrientation === "vertical") {
            teethRadius = beltWidth / 2;

            const leftX = beltX;
            const rightX = beltX + beltWidth;
            const topCenter = beltY + teethRadius;
            const bottomCenter = beltY + beltHeight - teethRadius;
            const startY = beltY + beltHeight / 2;

            straightLength = bottomCenter - topCenter;

            teethPath = `
                M ${rightX} ${startY}
                V ${bottomCenter}
                A ${teethRadius} ${teethRadius} 0 0 1 ${leftX} ${bottomCenter}
                V ${topCenter}
                A ${teethRadius} ${teethRadius} 0 0 1 ${rightX} ${topCenter}
                V ${startY}
            `;
        } else {
            teethRadius = beltHeight / 2;

            const topY = beltY;
            const bottomY = beltY + beltHeight;
            const leftCenter = beltX + teethRadius;
            const rightCenter = beltX + beltWidth - teethRadius;
            const startX = beltX + beltWidth / 2;

            straightLength = rightCenter - leftCenter;

            teethPath = `
                M ${startX} ${topY}
                H ${rightCenter}
                A ${teethRadius} ${teethRadius} 0 0 1 ${rightCenter} ${bottomY}
                H ${leftCenter}
                A ${teethRadius} ${teethRadius} 0 0 1 ${leftCenter} ${topY}
                H ${startX}
            `;
        }

        const actualPathLength =
            straightLength * 2 + Math.PI * teethRadius * 2;

        const toothCount = Math.max(
            1,
            Math.round(actualPathLength / toothPitch)
        );

        const cleanPathLength = toothCount * toothPitch;
        const toothPhase = toothWidth / 2;

        return {
            width,
            height,

            outerX,
            outerY,
            outerWidth,
            outerHeight,

            innerX,
            innerY,
            innerWidth: resolvedInnerWidth,
            innerHeight: resolvedInnerHeight,

            teethPath,
            cleanPathLength,
            toothPitch,
            toothPhase,
        };
    }, [
        contentSize.width,
        contentSize.height,
        contentPaddingX,
        contentPaddingY,
        innerWidth,
        innerHeight,
        minInnerWidth,
        minInnerHeight,
        orientation,
        minStraightLength,
        outerThickness,
        toothSpacingFromInner,
        teethThickness,
        toothWidth,
        toothGap,
    ]);

    const isMoving = direction !== "off" && toothSpeed > 0;

    const dashFrom =
        direction === "ccw"
            ? geometry.toothPhase - geometry.toothPitch
            : geometry.toothPhase;

    const dashTo =
        direction === "ccw"
            ? geometry.toothPhase
            : geometry.toothPhase - geometry.toothPitch;

    return (
        <div
            className={className}
            style={{
                position: "relative",
                display: "inline-block",
                width: geometry.width,
                height: geometry.height,
                ...style,
            }}
        >
            <svg
                viewBox={`0 0 ${geometry.width} ${geometry.height}`}
                className="w-full h-full"
                style={{
                    position: "absolute",
                    inset: 0,
                    pointerEvents: "none",
                    overflow: "visible",
                }}
            >
                <rect
                    x={geometry.outerX + outerBorderWidth / 2}
                    y={geometry.outerY + outerBorderWidth / 2}
                    width={geometry.outerWidth - outerBorderWidth}
                    height={geometry.outerHeight - outerBorderWidth}
                    rx={
                        Math.min(
                            geometry.outerWidth,
                            geometry.outerHeight
                        ) / 2
                    }
                    fill={outerFill}
                    stroke={outerStroke}
                    strokeWidth={outerBorderWidth}
                />

                <path
                    d={geometry.teethPath}
                    pathLength={geometry.cleanPathLength}
                    fill="none"
                    stroke={teethFill}
                    strokeWidth={teethThickness}
                    strokeLinecap="butt"
                    strokeDasharray={`${toothWidth} ${toothGap}`}
                    strokeDashoffset={geometry.toothPhase}
                >
                    {isMoving && (
                        <animate
                            attributeName="stroke-dashoffset"
                            from={dashFrom}
                            to={dashTo}
                            dur={`${toothSpeed}s`}
                            repeatCount="indefinite"
                        />
                    )}
                </path>

                <rect
                    x={geometry.innerX}
                    y={geometry.innerY}
                    width={geometry.innerWidth}
                    height={geometry.innerHeight}
                    rx={
                        Math.min(
                            geometry.innerWidth,
                            geometry.innerHeight
                        ) / 2
                    }
                    fill={innerFill}
                />
            </svg>

            <div
                className={contentClassName}
                style={{
                    position: "absolute",
                    left: geometry.innerX,
                    top: geometry.innerY,
                    width: geometry.innerWidth+1,
                    height: geometry.innerHeight+1,
                    display: "flex",
                    alignItems: "center",
                    justifyContent: "center",
                    padding: `${contentPaddingY}px ${contentPaddingX}px`,
                    boxSizing: "border-box",
                    borderRadius:
                        Math.min(
                            geometry.innerWidth,
                            geometry.innerHeight
                        ) / 2,
                    zIndex: 1,
                    overflow: "hidden",
                }}
            >
                <div
                    ref={contentRef}
                    className="inline-flex w-full h-full z-[2] items-center justify-center"
                >
                    {children}
                </div>
            </div>
        </div>
    );
}

export default ToothedFrame;