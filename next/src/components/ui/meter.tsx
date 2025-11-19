import React from "react";


interface MeterSvgProps extends React.HTMLAttributes<HTMLOrSVGElement> {
    meterColor?:string
    screenColor?:string
    baseColor?:string
    strokeColor?:string
    strokeWidth?:number
}
export const MeterSvg: React.FC<MeterSvgProps> = ({
    meterColor,
    screenColor,
    baseColor,
    strokeColor="#000000",
    strokeWidth=8,
    ...props
}) => (
    <svg
        version="1.0"
        xmlns="http://www.w3.org/2000/svg"
        viewBox="0 0 300 450"
        preserveAspectRatio="xMidYMid meet"
        {...props}
    >
        <rect
            x="0"
            y="0"
            width="300"
            height="450"
            fill="none"
            stroke="none"
            strokeWidth="1"
        />


        <g
            strokeWidth={strokeWidth}
            fill="none"
            stroke={strokeColor}
        >
            <path
                d="
                M0 10          
                Q0 0 10 0      
                H286     
                Q296 0 296 10  
                V20            
                H0             
                Z
            "
                transform="translate(2,428)"
                fill={baseColor}
                className={baseColor}
            />
            <path
                d="
                M0 10          
                Q0 0 10 0      
                H246     
                Q256 0 256 10  
                V18            
                H0             
                Z
            "
                transform="translate(22,410)"
                fill={baseColor}
                className={baseColor}
            />
            <path
                d="
                M0 40
                Q0 0 40 0      
                H180
                Q220 0 220 40  
                V400    
                H0             
                Z
            "
                transform="translate(40,8)"
                fill={meterColor}
                className={meterColor}
            />

            <rect
                y="50"
                x="50%"
                width="140"
                height="140"
                fill={screenColor}
                className={screenColor}
                stroke="black"
                rx="10"
                ry="10"
                style={{
                    transform: "translate(-50%,0)",
                    transformBox: "fill-box"
                }}
            />
        </g>
    </svg>
)

