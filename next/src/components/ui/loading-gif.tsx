import { cn } from "@/lib/utils";
import { cva, VariantProps } from "class-variance-authority";

const loadingGifVariants = cva(
    `flex flex-col items-center justify-center select-none justify-self-center
    rounded-[inherit] z-51 p-1 text-3xl
    `,
    {
        variants: {
            variant: {
                fit: "w-fit h-fit m-0 max-w-full max-h-full self-center absolute inset-0",
                fill: "size-full self-center absolute inset-0",
                full: "w-screen h-screen fixed inset-0"
            },

            size: {
                default: "[&>img]:h-50",
                sm: "[&>img]:h-30",
                xs: "[&>img]:h-20",
                lg: "[&>img]:h-70",
                xl: "[&>img]:h-80",
            },
            blur: {
                false: "",
                true: "backdrop-blur-[2px] bg-white/50",
                light: "backdrop-blur-[2px] bg-white/50"
            }
        },
        defaultVariants: {
            variant: "fill",
            size: "default",
            blur: false,
        }
    }
)

interface LoadingGifProps extends VariantProps<typeof loadingGifVariants>,React.HTMLAttributes<HTMLDivElement> {
    className?: string
    msg?: string
    src?: string
}

export const LoadingGif = ({ className, msg = "Loading...", src = "/running-cat.gif", variant, size, blur, ...divProps }: LoadingGifProps) => {
    return (
        <div className={cn(loadingGifVariants({ variant, size, blur, className }))} {...divProps}>
            <img
                src={src}
                alt=""
                className="max-w-full max-h-full min-w-0 min-h-0 rounded-full h-fit w-auto"
                onClick={(e) => {
                    e.currentTarget.animate(
                        [
                            { transform: "translateY(0)" },
                            { transform: "translateY(-50px)" },
                            { transform: "translateY(0)" },
                            { transform: "translateY(-30px)" },
                            { transform: "translateY(0)" },
                            { transform: "translateY(-5px)" },
                            { transform: "translateY(0)" },
                            { transform: "translateY(-2px)" },
                            { transform: "translateY(0)" }
                        ],
                        { duration: 1111, easing: "linear" }
                    );
                }}
                draggable={false}
            />
            {msg && <p className="text-inherit">{msg}</p>}
        </div> 
    )
}