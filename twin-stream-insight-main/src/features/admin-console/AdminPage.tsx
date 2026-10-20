import { ShieldAlert } from "lucide-react";
import { usePageTitle } from "@/hooks/usePageTitle";
import { useAuth } from "@/hooks/useAuth";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { roleAllows } from "../roles";
import { AccessPanel } from "./AccessPanel";
import { AuditPanel } from "./AuditPanel";
import { SystemPanel } from "./SystemPanel";
import { UsersPanel } from "./UsersPanel";
import { WebhooksPanel } from "./WebhooksPanel";

/**
 * `/admin`: users and roles, access requests (approve or reject viewer sign-ups), the audit log (filters, export), webhooks (add, change, test, delivery log) and system status.
 * Admin only. The role check here is a UX gate: it decides what is offered and sends no request for anyone else; the backend
 * answers 403 to every non-admin on every route regardless. Only the open tab's panel is mounted, so only its data is fetched.
 */
export default function AdminPage() {
  usePageTitle("Admin console");
  const { role } = useAuth();
  const allowed = roleAllows(role, "admin");

  if (!allowed) {
    return (
      <main className="mx-auto max-w-3xl space-y-3 p-4" data-testid="admin-page">
        <h1 className="text-xl font-semibold text-foreground">Admin console</h1>
        <p role="alert" className="flex items-start gap-2 text-sm text-foreground" data-testid="admin-denied">
          <ShieldAlert className="mt-0.5 h-4 w-4 shrink-0" aria-hidden="true" />
          Admin role required. Your account does not have access to this page.
        </p>
      </main>
    );
  }

  return (
    <main className="mx-auto max-w-6xl space-y-4 p-4" data-testid="admin-page">
      <header className="space-y-1">
        <h1 className="text-xl font-semibold text-foreground">Admin console</h1>
        <p className="text-sm text-muted-foreground">
          Every action here is recorded in the audit log. Nothing on this page changes the facility.
        </p>
      </header>
      <Tabs defaultValue="users" className="space-y-3">
        <TabsList className="h-auto max-w-full flex-wrap justify-start">
          <TabsTrigger value="users">Users</TabsTrigger>
          <TabsTrigger value="access">Access requests</TabsTrigger>
          <TabsTrigger value="audit">Audit log</TabsTrigger>
          <TabsTrigger value="webhooks">Webhooks</TabsTrigger>
          <TabsTrigger value="system">System</TabsTrigger>
        </TabsList>
        <TabsContent value="users"><UsersPanel /></TabsContent>
        <TabsContent value="access"><AccessPanel /></TabsContent>
        <TabsContent value="audit"><AuditPanel /></TabsContent>
        <TabsContent value="webhooks"><WebhooksPanel /></TabsContent>
        <TabsContent value="system"><SystemPanel /></TabsContent>
      </Tabs>
    </main>
  );
}
