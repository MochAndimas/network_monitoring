import { ProtectedPage } from "@/components/layout/protected-page";
import { IncidentsPage } from "@/features/incidents/incidents-page";
export default function Page(){return <ProtectedPage><IncidentsPage/></ProtectedPage>}
