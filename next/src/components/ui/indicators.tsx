import { cn } from '@/lib/utils';
import { cva } from 'class-variance-authority';

const ledStyles = cva('border-1 border-border rounded-[50%] shadow', {
    variants: {
        state: {
            on: 'bg-primary',
            off: 'bg-destructive',
            neutral: 'bg-muted',
            idle: 'bg-[#f3c562]',
        },
        size: {
            xs: 'size-2',
            sm: 'size-3',
            md: 'size-4',
            lg: 'size-5',
            xl: 'size-6',
        },
    },
    defaultVariants: {
        state: 'neutral',
        size: 'md',
    },
})

export type LedState = 'on' | 'off' | 'neutral' | 'idle' | boolean
export type LedSize = 'xs' | 'sm' | 'md' | 'lg' | 'xl'

export type LedProps = {
    state?: LedState
    size?: LedSize
}

export function Led({ state, size, className, ...props }: LedProps & React.HTMLAttributes<HTMLDivElement>) {
    const resolvedState: LedState = 
        typeof state === 'boolean' ? (state ? 'on' : 'neutral') : state ?? 'neutral'
    return <div className={cn(ledStyles({ state:resolvedState, size }), className)} {...props} />
}