import { FormEvent, useEffect, useMemo, useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useNavigate } from 'react-router-dom';
import { TopBar } from '@/components/layout/TopBar';
import { Section } from '@/components/shared/Section';
import { PageSkeleton } from '@/components/shared/Skeleton';
import { fetchCurrentFinancialSnapshot, saveFinancialSnapshot } from '@/lib/adapter';
import { fmtUSD } from '@/lib/format';
import { useTenantScopeKey } from '@/hooks/useTenantScope';
import { ArrowLeft, ReceiptText, Save, ShieldCheck, WalletCards } from 'lucide-react';
import type { FinancialSnapshot } from '@/types/domain';

const moneyFields: Array<{ key: keyof FinancialSnapshot; label: string; help: string; group: 'Assets' | 'Liabilities' | 'Monthly Cashflow' }> = [
  { key: 'cash_on_hand_usd', label: 'Cash on hand', help: 'USD in register, safe, or shop wallet today.', group: 'Assets' },
  { key: 'bank_balance_usd', label: 'Bank / wallet USD', help: 'Fresh USD in bank, card processor, or digital wallet.', group: 'Assets' },
  { key: 'receivables_usd', label: 'Customer receivables', help: 'Money customers owe you and you expect to collect.', group: 'Assets' },
  { key: 'equipment_fixtures_usd', label: 'Equipment and fixtures', help: 'Estimated resale value of shelves, POS, furniture, or equipment.', group: 'Assets' },
  { key: 'other_assets_usd', label: 'Other assets', help: 'Any other USD-value assets not counted above.', group: 'Assets' },
  { key: 'supplier_payables_usd', label: 'Supplier payables', help: 'Unpaid supplier invoices or purchase balances.', group: 'Liabilities' },
  { key: 'rent_payable_usd', label: 'Rent payable', help: 'Rent due or overdue.', group: 'Liabilities' },
  { key: 'salary_payable_usd', label: 'Salary payable', help: 'Staff or owner salary owed but not paid.', group: 'Liabilities' },
  { key: 'loan_balance_usd', label: 'Loan balance', help: 'Remaining loan, credit line, or informal borrowing balance.', group: 'Liabilities' },
  { key: 'tax_vat_payable_usd', label: 'Tax / VAT payable', help: 'Estimated tax or VAT amount owed.', group: 'Liabilities' },
  { key: 'customer_deposits_usd', label: 'Customer deposits', help: 'Deposits or credits customers paid for future delivery.', group: 'Liabilities' },
  { key: 'other_liabilities_usd', label: 'Other liabilities', help: 'Any other money the business owes.', group: 'Liabilities' },
  { key: 'monthly_sales_usd', label: 'Monthly sales', help: 'Total sales collected for this month.', group: 'Monthly Cashflow' },
  { key: 'monthly_expenses_usd', label: 'Monthly expenses', help: 'Rent, salaries, utilities, marketing, delivery, and other operating costs.', group: 'Monthly Cashflow' },
  { key: 'owner_draw_usd', label: 'Owner draw', help: 'Money taken out by the owner this month.', group: 'Monthly Cashflow' },
];

const emptySnapshot = (): FinancialSnapshot => ({
  period_month: new Date().toISOString().slice(0, 7),
  currency: 'USD',
  cash_on_hand_usd: 0,
  bank_balance_usd: 0,
  receivables_usd: 0,
  equipment_fixtures_usd: 0,
  other_assets_usd: 0,
  supplier_payables_usd: 0,
  rent_payable_usd: 0,
  salary_payable_usd: 0,
  loan_balance_usd: 0,
  tax_vat_payable_usd: 0,
  customer_deposits_usd: 0,
  other_liabilities_usd: 0,
  monthly_sales_usd: 0,
  monthly_expenses_usd: 0,
  owner_draw_usd: 0,
  notes: '',
});

const groupMeta = {
  Assets: {
    icon: WalletCards,
    tone: 'text-decision-promote',
    ring: 'border-decision-promote/25 bg-decision-promote/10',
    copy: 'Cash, bank balances, customer receivables, and owned business assets.',
  },
  Liabilities: {
    icon: ShieldCheck,
    tone: 'text-decision-clear',
    ring: 'border-decision-clear/25 bg-decision-clear/10',
    copy: 'Supplier balances, rent, salaries, loans, taxes, deposits, and other amounts owed.',
  },
  'Monthly Cashflow': {
    icon: ReceiptText,
    tone: 'text-primary-glow',
    ring: 'border-primary/25 bg-primary/10',
    copy: 'Sales collected, expenses paid, and owner withdrawals for the selected month.',
  },
} as const;

function SummaryMetric({ label, value, tone = 'text-panel-foreground' }: { label: string; value: string; tone?: string }) {
  return (
    <div className="rounded-lg border border-panel-border bg-white/5 px-4 py-3">
      <div className="text-[10.5px] font-mono uppercase tracking-[0.16em] text-panel-muted">{label}</div>
      <div className={`text-data text-[22px] leading-none mt-2 ${tone}`}>{value}</div>
    </div>
  );
}

function MoneyInput({ field, value, onChange }: {
  field: typeof moneyFields[number];
  value: number;
  onChange: (key: keyof FinancialSnapshot, value: number) => void;
}) {
  return (
    <label className="group block rounded-lg border border-panel-border bg-white/[0.045] px-4 py-3 transition hover:border-primary/35 hover:bg-white/[0.07] focus-within:border-primary/45 focus-within:shadow-glow/20">
      <span className="flex items-center justify-between gap-3">
        <span>
          <span className="block text-[13px] font-semibold text-panel-foreground">{field.label}</span>
          <span className="block text-[11.5px] text-panel-muted mt-0.5 leading-snug">{field.help}</span>
        </span>
        <span className="shrink-0 rounded border border-panel-border bg-black/20 px-1.5 py-0.5 text-[10px] font-mono font-semibold text-panel-muted">USD</span>
      </span>
      <input
        type="number"
        min="0"
        step="0.01"
        value={Number.isFinite(value) ? value : 0}
        onChange={(event) => onChange(field.key, Math.max(0, Number(event.target.value || 0)))}
        className="mt-3 h-10 w-full rounded-md border border-panel-border bg-background/70 px-3 text-[14px] text-panel-foreground outline-none transition focus:border-primary/50 focus:ring-2 focus:ring-primary/30"
      />
    </label>
  );
}

export default function UpdateFinancials() {
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const tenantScope = useTenantScopeKey();
  const [form, setForm] = useState<FinancialSnapshot>(emptySnapshot);

  const { data: currentSnapshot, isLoading } = useQuery({
    queryKey: ['financial-current-snapshot', tenantScope],
    queryFn: fetchCurrentFinancialSnapshot,
    staleTime: 30_000,
  });

  useEffect(() => {
    if (currentSnapshot?.snapshot) {
      setForm({ ...emptySnapshot(), ...currentSnapshot.snapshot, period_month: currentSnapshot.snapshot.period_month.slice(0, 7) });
    } else if (currentSnapshot?.period_month) {
      setForm((current) => ({ ...current, period_month: currentSnapshot.period_month.slice(0, 7) }));
    }
  }, [currentSnapshot]);

  const totals = useMemo(() => {
    const assets = form.cash_on_hand_usd + form.bank_balance_usd + form.receivables_usd + form.equipment_fixtures_usd + form.other_assets_usd;
    const liabilities = form.supplier_payables_usd + form.rent_payable_usd + form.salary_payable_usd + form.loan_balance_usd + form.tax_vat_payable_usd + form.customer_deposits_usd + form.other_liabilities_usd;
    const monthlyOut = form.monthly_expenses_usd + form.owner_draw_usd;
    return { assets, liabilities, equity: assets - liabilities, runway: monthlyOut > 0 ? (form.cash_on_hand_usd + form.bank_balance_usd) / monthlyOut : 0 };
  }, [form]);

  const mutation = useMutation({
    mutationFn: () => saveFinancialSnapshot(form.period_month, form),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['financial-current-snapshot'] });
      queryClient.invalidateQueries({ queryKey: ['financial-balance-sheet'] });
      queryClient.invalidateQueries({ queryKey: ['financial-progress'] });
      navigate('/financial/balance-sheet');
    },
  });

  const updateValue = (key: keyof FinancialSnapshot, value: number) => setForm((current) => ({ ...current, [key]: value }));

  const submit = (event: FormEvent) => {
    event.preventDefault();
    mutation.mutate();
  };

  return (
    <>
      <TopBar
        title="Update Financials"
        subtitle="Monthly USD snapshot for this retailer"
        actions={<button onClick={() => navigate('/financial')} className="flex items-center gap-1.5 text-[13px] text-muted-foreground hover:text-foreground"><ArrowLeft className="h-4 w-4" /> Back</button>}
      />
      <main className="flex-1 px-6 lg:px-8 py-6 space-y-6 animate-fade-in">
        {isLoading && <PageSkeleton />}
        {!isLoading && (
          <form onSubmit={submit} className="space-y-6">
            <div className="relative panel-dark rounded-2xl overflow-hidden shadow-lg-soft">
              <div className="absolute inset-0 opacity-30" style={{
                background: 'radial-gradient(700px 260px at 78% -20%, hsl(38 100% 62% / 0.34), transparent), radial-gradient(620px 260px at 8% 115%, hsl(158 65% 36% / 0.25), transparent)',
              }} />
              <div className="relative grid gap-6 p-5 lg:grid-cols-[0.9fr_1.4fr] lg:p-6">
                <div>
                  <div className="inline-flex items-center gap-2 text-[10.5px] font-mono uppercase tracking-[0.2em] text-panel-muted">
                    <span className="h-1.5 w-1.5 rounded-full bg-decision-promote" /> USD Snapshot
                  </div>
                  <h2 className="font-display text-[26px] leading-tight text-panel-foreground mt-3">Update this retailer's financial position.</h2>
                  <p className="mt-3 max-w-xl text-[13px] leading-relaxed text-panel-muted">
                    Enter the month-end numbers the owner can answer quickly. Inventory value is still calculated from live stock; this snapshot fills in cash, debt, and operating movement.
                  </p>
                  <label className="mt-5 block max-w-xs">
                    <span className="block text-[10.5px] font-mono uppercase tracking-[0.16em] text-panel-muted mb-2">Snapshot month</span>
                    <input
                      type="month"
                      value={form.period_month}
                      onChange={(event) => setForm((current) => ({ ...current, period_month: event.target.value }))}
                      className="h-10 w-full rounded-md border border-panel-border bg-black/20 px-3 text-[14px] text-panel-foreground outline-none transition focus:border-primary/50 focus:ring-2 focus:ring-primary/30"
                    />
                  </label>
                </div>
                <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
                  <SummaryMetric label="Assets" value={fmtUSD(totals.assets)} tone="text-decision-promote" />
                  <SummaryMetric label="Liabilities" value={fmtUSD(totals.liabilities)} tone="text-decision-clear" />
                  <SummaryMetric label="Equity" value={fmtUSD(totals.equity)} />
                  <SummaryMetric label="Runway" value={`${totals.runway.toFixed(1)} mo`} tone="text-primary-glow" />
                </div>
              </div>
            </div>

            {(['Assets', 'Liabilities', 'Monthly Cashflow'] as const).map((group) => (
              <Section
                key={group}
                variant="panel"
                title={group}
                subtitle={groupMeta[group].copy}
                action={(() => {
                  const Icon = groupMeta[group].icon;
                  return <div className={`h-9 w-9 rounded-lg border flex items-center justify-center ${groupMeta[group].ring}`}><Icon className={`h-4 w-4 ${groupMeta[group].tone}`} /></div>;
                })()}
              >
                <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-3">
                  {moneyFields.filter((field) => field.group === group).map((field) => (
                    <MoneyInput key={String(field.key)} field={field} value={Number(form[field.key] || 0)} onChange={updateValue} />
                  ))}
                </div>
              </Section>
            ))}

            <Section variant="panel" title="Notes" subtitle="Optional context for this month">
              <textarea
                value={form.notes ?? ''}
                onChange={(event) => setForm((current) => ({ ...current, notes: event.target.value }))}
                className="min-h-24 w-full rounded-md border border-panel-border bg-background/70 px-3 py-2 text-[14px] text-panel-foreground outline-none transition focus:border-primary/50 focus:ring-2 focus:ring-primary/30"
              />
            </Section>

            {mutation.isError && <div className="rounded-lg border border-destructive/40 bg-destructive/5 px-4 py-3 text-[13px] text-destructive">{(mutation.error as Error).message}</div>}
            <div className="flex justify-end">
              <button type="submit" disabled={mutation.isPending} className="inline-flex h-10 items-center gap-2 rounded-md bg-primary-glow px-4 text-[13px] font-semibold text-primary-foreground shadow-glow hover:opacity-90 disabled:opacity-50">
                <Save className="h-4 w-4" /> {mutation.isPending ? 'Saving...' : 'Save Financials'}
              </button>
            </div>
          </form>
        )}
      </main>
    </>
  );
}
