import { ProtectedPage } from "@/components/layout/protected-page";
import { DailySummaryPage } from "@/features/daily-summary/daily-summary-page";
export default function Page() { return <ProtectedPage><DailySummaryPage /></ProtectedPage>; }
