import { OverviewPage } from "@/features/overview/overview-page";
import { ProtectedPage } from "@/components/layout/protected-page";

export default function Page() {
  return <ProtectedPage><OverviewPage /></ProtectedPage>;
}
