import { ProtectedPage } from "@/components/layout/protected-page";
import { AccountsPage } from "@/features/accounts/accounts-page";

export default function Page() {
  return <ProtectedPage><AccountsPage /></ProtectedPage>;
}
