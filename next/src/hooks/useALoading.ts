import React from "react"

export function useALoading() {
    const [loading, setLoading] = React.useState(false);

    const withLoading = React.useCallback(
        <TArgs extends unknown[], TResult>(
            fn: (...args: TArgs) => Promise<TResult>
        ) =>
            async (...args: TArgs): Promise<TResult> => {
                setLoading(true);
                try {
                    return await fn(...args);
                } finally {
                    setLoading(false);
                }
            },
        []
    );

    return {
        loading,
        setLoading,
        withLoading,
    };
}