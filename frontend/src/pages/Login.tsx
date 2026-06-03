import { FormEvent, useState } from 'react';
import { Link, useLocation, useNavigate } from 'react-router-dom';
import { Radar } from 'lucide-react';
import { toast } from 'sonner';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { loginAccount } from '@/lib/adapter';
import { useAuth } from '@/store/auth';
import { useSettings } from '@/store/settings';

export default function Login() {
  const navigate = useNavigate();
  const location = useLocation();
  const setSession = useAuth((state) => state.setSession);
  const setMode = useSettings((state) => state.setMode);
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [loading, setLoading] = useState(false);

  const from = typeof location.state === 'object' && location.state && 'from' in location.state
    ? String(location.state.from || '/overview')
    : '/overview';

  async function onSubmit(event: FormEvent) {
    event.preventDefault();
    setLoading(true);
    try {
      const session = await loginAccount(email, password);
      setSession(session.access_token, session.user);
      setMode('eep-live');
      navigate(from, { replace: true });
    } catch (error: any) {
      toast.error(error?.message || 'Login failed');
    } finally {
      setLoading(false);
    }
  }

  return (
    <main className="min-h-screen bg-background text-foreground grid place-items-center px-6">
      <Card className="w-full max-w-md">
        <CardHeader>
          <div className="mb-4 h-11 w-11 rounded-lg bg-gradient-data flex items-center justify-center">
            <Radar className="h-6 w-6 text-primary-foreground" />
          </div>
          <CardTitle>Log in</CardTitle>
          <CardDescription>Use your admin or shop owner account.</CardDescription>
        </CardHeader>
        <CardContent>
          <form onSubmit={onSubmit} className="space-y-4">
            <div className="space-y-2">
              <Label htmlFor="email">Email</Label>
              <Input id="email" type="email" value={email} onChange={(event) => setEmail(event.target.value)} required />
            </div>
            <div className="space-y-2">
              <Label htmlFor="password">Password</Label>
              <Input id="password" type="password" value={password} onChange={(event) => setPassword(event.target.value)} required />
            </div>
            <Button type="submit" className="w-full" disabled={loading}>
              {loading ? 'Logging in...' : 'Log in'}
            </Button>
          </form>
          <div className="mt-5 text-sm text-muted-foreground">
            New shop? <Link to="/signup" className="text-primary font-medium hover:underline">Create shop account</Link>
          </div>
        </CardContent>
      </Card>
    </main>
  );
}
