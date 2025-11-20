import React from "react"

type Procedure<T extends any[]> = (...args: T) => void;

export function useDebounce<T extends any[]>(action: Procedure<T>, delay = 100) {
    const timeoutRef = React.useRef<ReturnType<typeof setTimeout> | null>(null);

    const debouncedAction = React.useCallback((...args: T) => {
        if (timeoutRef.current) clearTimeout(timeoutRef.current);

        timeoutRef.current = setTimeout(() => {
            action(...args);
        }, delay);
    }, [action, delay]);

    return debouncedAction;
}
