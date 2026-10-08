"use client";

import { useEffect, useState } from "react";
import { format } from "date-fns";
import { Loader2, Zap, CheckCircle2, AlertCircle, ArrowUpRight, Check } from "lucide-react";
import { Card, CardContent, CardDescription, CardHeader, CardTitle, CardFooter } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { subscriptionService } from "@/services/subscription.service";
import { paymentService } from "@/services/payment.service";
import { Subscription, CreditTransaction, PlanConfig } from "@/types/subscription";

export default function SubscriptionPage() {
  const [subscription, setSubscription] = useState<Subscription | null>(null);
  const [history, setHistory] = useState<CreditTransaction[]>([]);
  const [plans, setPlans] = useState<Record<string, PlanConfig>>({});
  
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(false);
  const [upgradingPlan, setUpgradingPlan] = useState<string | null>(null);
  const [upgradeSuccess, setUpgradeSuccess] = useState<string | null>(null);

  useEffect(() => {
    async function loadData() {
      try {
        setLoading(true);
        setError(false);
        const [sub, hist, availablePlans] = await Promise.all([
          subscriptionService.getMySubscription(),
          subscriptionService.getCreditTransactions(),
          subscriptionService.getPlans()
        ]);
        setSubscription(sub);
        setHistory(hist);
        setPlans(availablePlans);
      } catch (err) {
        console.error("Failed to load subscription data", err);
        setError(true);
      } finally {
        setLoading(false);
      }
    }
    loadData();
  }, []);

  const handleUpgrade = async (planId: string) => {
    try {
      setUpgradingPlan(planId);
      const response = await paymentService.createPayment(planId);
      
      if (response.payment_url) {
        window.location.href = response.payment_url;
      } else {
        throw new Error("Invalid payment URL returned");
      }
    } catch (err: any) {
      console.error("Failed to initiate payment", err);
      
      if (err?.response?.status === 401) {
        window.location.href = '/login/user';
      } else {
        alert("Failed to initiate secure payment. Please try again.");
      }
      setUpgradingPlan(null);
    }
  };

  if (loading) {
    return (
      <div className="flex items-center justify-center h-full min-h-[400px]">
        <Loader2 className="w-8 h-8 animate-spin text-brand-purple" />
      </div>
    );
  }

  if (error || !subscription) {
    return (
      <div className="flex flex-col items-center justify-center h-full min-h-[400px] text-text-muted space-y-4">
        <AlertCircle className="w-12 h-12 text-red-400" />
        <p className="text-lg">Unable to load billing information. Please try again.</p>
        <Button onClick={() => window.location.reload()} variant="outline">Retry</Button>
      </div>
    );
  }

  const currentPlanId = subscription.plan_id || "FREE";
  
  return (
    <div className="max-w-6xl mx-auto space-y-8 animate-in fade-in duration-500 py-6">
      <div>
        <h1 className="text-3xl font-bold tracking-tight text-white mb-2">Subscription & Billing</h1>
        <p className="text-text-muted">Manage your AI usage and upgrade to unlock more limits.</p>
      </div>

      {upgradeSuccess && (
        <div className="p-4 bg-green-500/10 border border-green-500/30 text-green-500 rounded-lg flex items-center gap-2">
          <CheckCircle2 className="w-5 h-5" />
          {upgradeSuccess}
        </div>
      )}

      {/* Overview Section */}
      <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-4">
        <Card className="bg-surface border-border shadow-md">
          <CardHeader className="pb-2">
            <CardTitle className="text-sm font-medium text-text-muted">Current Plan</CardTitle>
          </CardHeader>
          <CardContent>
            <div className="text-2xl font-bold text-white uppercase">{currentPlanId}</div>
            <p className="text-xs text-brand-purple mt-1 flex items-center gap-1">
              Status: <span className="uppercase font-semibold">{subscription.status}</span>
            </p>
          </CardContent>
        </Card>
        
        <Card className="bg-surface border-border shadow-md relative overflow-hidden">
          <div className="absolute right-0 top-0 w-16 h-16 bg-brand-purple/10 rounded-bl-full blur-xl" />
          <CardHeader className="pb-2">
            <CardTitle className="text-sm font-medium text-text-muted">Credits Remaining</CardTitle>
          </CardHeader>
          <CardContent>
            <div className="text-3xl font-bold text-brand-purple flex items-center gap-2">
              <Zap className="h-6 w-6 fill-brand-purple" />
              {subscription.credits_remaining}
              <span className="text-sm text-text-muted font-normal">/ {subscription.plan_details?.credits || 0}</span>
            </div>
          </CardContent>
        </Card>

        <Card className="bg-surface border-border shadow-md">
          <CardHeader className="pb-2">
            <CardTitle className="text-sm font-medium text-text-muted">Posts Created</CardTitle>
          </CardHeader>
          <CardContent>
            <div className="text-2xl font-bold text-white">
              {subscription.usage?.posts_created ?? 0} 
              <span className="text-sm text-text-muted font-normal ml-1">/ {subscription.plan_details?.post_limit === -1 ? '∞' : (subscription.plan_details?.post_limit ?? 0)}</span>
            </div>
          </CardContent>
        </Card>

        <Card className="bg-surface border-border shadow-md">
          <CardHeader className="pb-2">
            <CardTitle className="text-sm font-medium text-text-muted">Reels Created</CardTitle>
          </CardHeader>
          <CardContent>
            <div className="text-2xl font-bold text-white">
              {subscription.usage?.reels_created ?? 0}
              <span className="text-sm text-text-muted font-normal ml-1">/ {subscription.plan_details?.reel_limit === -1 ? '∞' : (subscription.plan_details?.reel_limit ?? 0)}</span>
            </div>
          </CardContent>
        </Card>
      </div>

      {/* Plans Section */}
      <div>
        <h2 className="text-xl font-bold text-white mb-6 flex items-center gap-2">
          <ArrowUpRight className="w-5 h-5 text-brand-purple" />
          Available Plans
        </h2>
        <div className={`grid gap-6 md:grid-cols-2 lg:grid-cols-3 ${
          Object.keys(plans).length === 4 ? "xl:grid-cols-4" : 
          Object.keys(plans).length === 3 ? "xl:grid-cols-3" : 
          "xl:grid-cols-5"
        }`}>
          {Object.entries(plans).map(([planId, plan]) => {
            const isCurrentPlan = String(currentPlanId).toLowerCase() === String(planId).toLowerCase();
            return (
              <Card 
                key={planId} 
                className={`bg-surface flex flex-col relative transition-all duration-300 ${isCurrentPlan ? "border-brand-purple shadow-[0_0_20px_rgba(190,50,255,0.15)] scale-[1.02]" : "border-border hover:border-border-hover hover:-translate-y-1"}`}
              >
                {isCurrentPlan && (
                  <div className="absolute -top-3 left-1/2 -translate-x-1/2 px-3 py-1 bg-brand-purple text-white text-xs font-bold rounded-full shadow-lg whitespace-nowrap">
                    CURRENT PLAN
                  </div>
                )}
                <CardHeader>
                  <CardTitle className="text-lg uppercase tracking-wide">{plan.name}</CardTitle>
                  <div className="mt-2 flex items-baseline gap-1">
                    <span className="text-3xl font-bold text-white">₹{plan.price}</span>
                    <span className="text-text-muted text-sm">/mo</span>
                    {plan.price > 0 && <span className="text-xs font-semibold text-brand-purple/80 ml-1">+ 18% GST</span>}
                  </div>
                </CardHeader>
                <CardContent className="flex-1 space-y-4">
                  <div className="flex items-center gap-2 text-brand-purple font-semibold bg-brand-purple/10 p-2 rounded-md">
                    <Zap className="h-4 w-4" />
                    <span>{plan.credits} credits</span>
                  </div>
                  <ul className="space-y-2 text-sm text-text-muted">
                    <li className="flex items-center gap-2">
                      <Check className="w-4 h-4 text-green-400 shrink-0" />
                      {plan.post_limit === -1 ? 'Unlimited' : plan.post_limit} Posts / mo
                    </li>
                    <li className="flex items-center gap-2">
                      <Check className="w-4 h-4 text-green-400 shrink-0" />
                      {plan.reel_limit === -1 ? 'Unlimited' : plan.reel_limit} Reels / mo
                    </li>
                    {plan.watermark ? (
                      <li className="flex items-center gap-2 text-text-muted/50 line-through">
                        <Check className="w-4 h-4 shrink-0" /> No Watermarks
                      </li>
                    ) : (
                      <li className="flex items-center gap-2">
                        <Check className="w-4 h-4 text-green-400 shrink-0" /> No Watermarks
                      </li>
                    )}
                    {plan.team_members > 1 && (
                      <li className="flex items-center gap-2">
                        <Check className="w-4 h-4 text-green-400 shrink-0" /> Team Members: {plan.team_members}
                      </li>
                    )}
                  </ul>
                </CardContent>
                <CardFooter>
                  {isCurrentPlan ? (
                    <Button className="w-full bg-surface-elevated text-brand-purple cursor-default" variant="secondary">
                      Active
                    </Button>
                  ) : (
                    <Button 
                      className="w-full bg-brand-gradient text-white hover:opacity-90 disabled:opacity-70" 
                      onClick={() => handleUpgrade(planId)}
                      disabled={upgradingPlan !== null}
                    >
                      {upgradingPlan === planId ? (
                        <>
                          <Loader2 className="w-4 h-4 animate-spin mr-2" />
                          Preparing Payment...
                        </>
                      ) : "Upgrade"}
                    </Button>
                  )}
                </CardFooter>
              </Card>
            );
          })}
        </div>
      </div>

      {/* History Section */}
      <div>
        <h2 className="text-xl font-bold text-white mb-4">Credit Transactions</h2>
        <Card className="bg-surface border-border overflow-hidden">
          {history.length === 0 ? (
            <CardContent className="py-8 text-center text-text-muted">
              No credit transactions found.
            </CardContent>
          ) : (
            <div className="overflow-x-auto">
              <table className="w-full text-sm text-left text-text-muted">
                <thead className="text-xs uppercase bg-surface-elevated/50 text-text-muted border-b border-border">
                  <tr>
                    <th className="px-6 py-4 font-medium">Date</th>
                    <th className="px-6 py-4 font-medium">Action</th>
                    <th className="px-6 py-4 font-medium">Credits</th>
                    <th className="px-6 py-4 font-medium">Balance After</th>
                  </tr>
                </thead>
                <tbody>
                  {history.map((tx, idx) => (
                    <tr key={tx.id || idx} className="border-b border-border/50 hover:bg-surface-elevated/20 transition-colors">
                      <td className="px-6 py-4">{format(new Date(tx.created_at), "MMM d, yyyy h:mm a")}</td>
                      <td className="px-6 py-4 font-medium text-white">{tx.action || (tx as any).transaction_type || (tx as any).feature}</td>
                      <td className={`px-6 py-4 font-bold ${tx.amount < 0 ? 'text-red-400' : 'text-green-400'}`}>
                        {tx.amount > 0 ? '+' : ''}{tx.amount}
                      </td>
                      <td className="px-6 py-4">{tx.balance_after}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </Card>
      </div>
    </div>
  );
}
