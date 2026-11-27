import * as DialogPrimitive from '@radix-ui/react-dialog';
import { X } from 'lucide-react';
import { useTranslation } from 'react-i18next';
import { forwardRef, type ComponentPropsWithoutRef, type ElementRef } from 'react';
import { cn } from '../../lib/utils';

const Dialog = DialogPrimitive.Root;
const DialogTrigger = DialogPrimitive.Trigger;
const DialogPortal = DialogPrimitive.Portal;
const DialogClose = DialogPrimitive.Close;

const DialogOverlay = forwardRef<
  ElementRef<typeof DialogPrimitive.Overlay>,
  ComponentPropsWithoutRef<typeof DialogPrimitive.Overlay>
>(({ className, ...props }, ref) => (
  <DialogPrimitive.Overlay
    ref={ref}
    className={cn('fixed inset-0 z-nx-modal bg-nx-overlay', className)}
    {...props}
  />
));
DialogOverlay.displayName = 'DialogOverlay';

export interface DialogContentProps extends ComponentPropsWithoutRef<typeof DialogPrimitive.Content> {
  /** Extra classes for the full-screen centering wrapper (direction-neutral flex). */
  containerClassName?: string;
  /** Show the built-in close button (default true). */
  showClose?: boolean;
}

const DialogContent = forwardRef<ElementRef<typeof DialogPrimitive.Content>, DialogContentProps>(
  ({ className, containerClassName, showClose = true, children, ...props }, ref) => {
    const { t } = useTranslation();
    return (
      <DialogPortal>
        <DialogOverlay />
        <div
          className={cn(
            'pointer-events-none fixed inset-0 z-nx-modal flex items-center justify-center p-4',
            containerClassName,
          )}
        >
          <DialogPrimitive.Content
            ref={ref}
            className={cn(
              'pointer-events-auto relative w-full max-w-lg rounded-nx-lg border border-nx-border bg-nx-surface p-6 shadow-nx-lg focus:outline-none',
              className,
            )}
            {...props}
          >
            {children}
            {showClose && (
              <DialogPrimitive.Close
                aria-label={t('dialog.close')}
                className="absolute end-4 top-4 rounded-nx-sm text-nx-fg-muted hover:text-nx-fg focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-nx-focus"
              >
                <X className="h-4 w-4" aria-hidden="true" />
              </DialogPrimitive.Close>
            )}
          </DialogPrimitive.Content>
        </div>
      </DialogPortal>
    );
  },
);
DialogContent.displayName = 'DialogContent';

const DialogTitle = forwardRef<
  ElementRef<typeof DialogPrimitive.Title>,
  ComponentPropsWithoutRef<typeof DialogPrimitive.Title>
>(({ className, ...props }, ref) => (
  <DialogPrimitive.Title
    ref={ref}
    className={cn('text-base font-semibold text-nx-fg', className)}
    {...props}
  />
));
DialogTitle.displayName = 'DialogTitle';

const DialogDescription = forwardRef<
  ElementRef<typeof DialogPrimitive.Description>,
  ComponentPropsWithoutRef<typeof DialogPrimitive.Description>
>(({ className, ...props }, ref) => (
  <DialogPrimitive.Description
    ref={ref}
    className={cn('text-sm text-nx-fg-muted', className)}
    {...props}
  />
));
DialogDescription.displayName = 'DialogDescription';

export { Dialog, DialogTrigger, DialogClose, DialogContent, DialogTitle, DialogDescription };
