import { useState, useEffect, useRef } from 'react';

type UseCountdownReturn = [number, React.Dispatch<React.SetStateAction<number>>];

export function useCountdown(
    onComplete?: () => void | Promise<void>
): UseCountdownReturn {
    const [seconds, setSeconds] = useState<number>(-1);
    const callbackRef = useRef(onComplete);

    // Keep callback ref updated
    useEffect(() => {
        callbackRef.current = onComplete;
    }, [onComplete]);

    useEffect(() => {
        if (seconds <= 0) {
            if (seconds === 0 && callbackRef.current) {
                // Wrap in async IIFE to await callback
                (async () => {
                    await callbackRef.current?.();
                })();
            }
            return;
        }

        const interval = setInterval(() => {
            setSeconds(prev => {
                if (prev <= 1) {
                    clearInterval(interval);
                    if (callbackRef.current) {
                        (async () => {
                            await callbackRef.current?.();
                        })();
                    }
                    return 0;
                }
                return prev - 1;
            });
        }, 1000);

        return () => clearInterval(interval);
    }, [seconds]);

    return [seconds, setSeconds];
}
