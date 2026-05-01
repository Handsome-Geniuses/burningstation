import React from "react";
import {
    CircleAlertIcon,
    CircleCheckIcon,
    CircleXIcon,
    InfoIcon,
    Loader2,
} from "lucide-react";
import { cva } from "class-variance-authority";
import { toast } from "sonner";
import { cn } from "@/lib/utils";

export type NotifyType = "message" | "info" | "warn" | "error" | "success";

type NotifyAction = {
    label: string;
    onClick: () => void;
};

export type NotifyOptions = {
    description?: string;
    duration?: number;
    action?: NotifyAction;
    className?: string;
    textClassName?: string;
    descriptionClassName?: string;
    iconClassName?: string;
    toasterId?: string;
};

type NotifyOptionsResolver<T> =
    | NotifyOptions
    | ((value: T) => NotifyOptions | undefined);

function resolveNotifyOptions<T>(
    resolver: NotifyOptionsResolver<T> | undefined,
    value: T
): NotifyOptions | undefined {
    if (typeof resolver === "function") {
        return resolver(value);
    }

    return resolver;
}

const wrapVariants = cva("min-w-64");
const textVariants = cva("ml-2.5 w-full text-lg", {
    variants: {
        tone: {
            message: "",
            info: "text-foreground",
            warn: "text-[#f3c562]",
            error: "text-destructive",
            success: "text-primary",
            loading: "",
        },
    },
    defaultVariants: {
        tone: "message",
    },
});

const descriptionVariants = cva("ml-2.5 text-sm text-muted-foreground");
const iconVariants = cva("rounded-full border-0 text-[1.8em]", {
    variants: {
        tone: {
            message: "",
            info: "bg-foreground text-background",
            warn: "bg-[#f3c562] text-background",
            error: "bg-destructive text-background",
            success: "bg-primary text-background",
            loading: "",
        },
    },
    defaultVariants: {
        tone: "message",
    },
});

function renderIcon(
    tone: "info" | "warn" | "error" | "success" | "loading",
    iconClassName?: string
) {
    const className = cn(iconVariants({ tone }), iconClassName);

    switch (tone) {
        case "info":
            return <InfoIcon className={className} />;
        case "warn":
            return <CircleAlertIcon className={className} />;
        case "error":
            return <CircleXIcon className={className} />;
        case "success":
            return <CircleCheckIcon className={className} />;
        case "loading":
            return <Loader2 className={cn("ml-2.5 animate-spin", iconClassName)} />;
    }
}

function base(
    tone: "message" | "info" | "warn" | "error" | "success" | "loading",
    msg: string,
    opts: NotifyOptions = {}
) {
    const {
        description,
        duration,
        action,
        className,
        textClassName,
        descriptionClassName,
        iconClassName,
        toasterId,
    } = opts;

    const icon =
        tone === "message" ? undefined : renderIcon(tone, iconClassName);

    return toast.message(
        <div className="flex flex-col" >
            <p className={cn(textVariants({ tone }), textClassName)
            }> {msg} </p>
            {
                description ? (
                    <p className={cn(descriptionVariants(), descriptionClassName)
                    }>
                        {description}
                    </p>
                ) : null}
        </div>,
        {
            className: cn(wrapVariants(), className),
            duration,
            icon,
            action,
            toasterId,
        }
    );
}

const message = (msg: string, opts?: NotifyOptions) =>
    base("message", msg, opts);

const info = (msg: string, opts?: NotifyOptions) => base("info", msg, opts);

const warn = (msg: string, opts?: NotifyOptions) => base("warn", msg, opts);

const error = (msg: string, opts?: NotifyOptions) => base("error", msg, opts);

const success = (msg: string, opts?: NotifyOptions) =>
    base("success", msg, opts);

const loading = (msg: string, opts?: NotifyOptions) =>
    base("loading", msg, opts);

const noticeMap: Record<Exclude<NotifyType, "message">, typeof info> = {
    info,
    warn,
    error,
    success,
};

const notice = (
    type: Exclude<NotifyType, "message">,
    msg: string,
    opts?: NotifyOptions
) => {
    return noticeMap[type](msg, opts);
};

function promise<T>(
    p: Promise<T>,
    messages: {
        loading: string;
        success: string;
        error: string;
        loadingOptions?: NotifyOptions;
        successOptions?: NotifyOptionsResolver<T>;
        errorOptions?: NotifyOptionsResolver<unknown>;
    }
) {
    const id = loading(messages.loading, messages.loadingOptions);

    return p
        .then((result) => {
            toast.dismiss(id);
            success(
                messages.success,
                resolveNotifyOptions(messages.successOptions, result)
            );
            return result;
        })
        .catch((err) => {
            toast.dismiss(id);
            error(
                messages.error,
                resolveNotifyOptions(messages.errorOptions, err)
            );
            throw err;
        });
}

export const notify = {
    message,
    info,
    warn,
    error,
    success,
    loading,
    notice,
    promise,
};
