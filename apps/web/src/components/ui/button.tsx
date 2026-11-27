import { Slot } from '@radix-ui/react-slot';
import { cva, type VariantProps } from 'class-variance-authority';
import { forwardRef, type ButtonHTMLAttributes } from 'react';
import { cn } from '../../lib/utils';

const buttonVariants = cva(
  'inline-flex items-center justify-center gap-2 whitespace-nowrap rounded-nx-md text-sm font-medium transition-colors disabled:pointer-events-none disabled:opacity-50 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-nx-focus',
  {
    variants: {
      variant: {
        default: 'bg-nx-primary text-nx-primary-fg hover:opacity-90',
        outline: 'border border-nx-border bg-nx-surface text-nx-fg hover:bg-nx-surface-raised',
        ghost: 'text-nx-fg-muted hover:bg-nx-surface-raised hover:text-nx-fg',
      },
      size: {
        default: 'h-9 px-4 py-2',
        sm: 'h-8 rounded-nx-sm px-3 text-xs',
        icon: 'h-9 w-9',
      },
    },
    defaultVariants: {
      variant: 'default',
      size: 'default',
    },
  },
);

export interface ButtonProps
  extends ButtonHTMLAttributes<HTMLButtonElement>,
    VariantProps<typeof buttonVariants> {
  asChild?: boolean;
}

/** shadcn/ui-style button built on cva with --nx-* token classes only. */
export const Button = forwardRef<HTMLButtonElement, ButtonProps>(
  ({ className, variant, size, asChild = false, ...props }, ref) => {
    const Comp = asChild ? Slot : 'button';
    return <Comp ref={ref} className={cn(buttonVariants({ variant, size }), className)} {...props} />;
  },
);
Button.displayName = 'Button';
