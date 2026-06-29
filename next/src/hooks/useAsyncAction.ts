import React from "react";

export function useAsyncAction() {
    const [running, setRunning] = React.useState(false);
    const [error, setError] = React.useState<unknown>(null);

    const run = React.useCallback(
        <TResult,>(fn: () => Promise<TResult>) =>
            async () => {
                setRunning(true);
                setError(null);

                try {
                    return await fn();
                } catch (err) {
                    setError(err);
                    throw err;
                } finally {
                    setRunning(false);
                }
            },
        []
    );

    return { running, error, run };
}