import { cn } from '@/lib/utils';

interface Props {
  title?: string;
  subtitle?: string;
  action?: React.ReactNode;
  children: React.ReactNode;
  className?: string;
  bodyClassName?: string;
  variant?: 'default' | 'panel';
}

export function Section({ title, subtitle, action, children, className, bodyClassName, variant = 'default' }: Props) {
  return (
    <section
      className={cn(
        'rounded-xl border shadow-sm-soft overflow-hidden',
        variant === 'panel' ? 'panel-dark' : 'bg-card border-border',
        className
      )}
    >
      {(title || action) && (
        <div className={cn(
          'flex items-center justify-between gap-4 px-5 py-4 border-b',
          variant === 'panel' ? 'border-panel-border' : 'border-border'
        )}>
          <div className="min-w-0">
            {title && (
              <h3 className={cn(
                'font-display text-[14.5px] font-semibold tracking-tight',
                variant === 'panel' ? 'text-panel-foreground' : 'text-foreground'
              )}>
                {title}
              </h3>
            )}
            {subtitle && (
              <p className={cn(
                'text-[12.5px] mt-0.5',
                variant === 'panel' ? 'text-panel-muted' : 'text-muted-foreground'
              )}>
                {subtitle}
              </p>
            )}
          </div>
          {action}
        </div>
      )}
      <div className={cn('p-5', bodyClassName)}>{children}</div>
    </section>
  );
}
