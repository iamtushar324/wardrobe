import { useQuery } from "@tanstack/react-query";
import { createContext, useContext } from "react";
import { Navigate, Route, Routes } from "react-router-dom";
import { api, ApiError, type Config, type Me } from "./api";
import Layout from "./components/Layout";
import Closet from "./pages/Closet";
import Inbox, { BatchReview } from "./pages/Inbox";
import ItemPage from "./pages/Item";
import Login from "./pages/Login";
import PhotoPage from "./pages/Photo";
import Settings from "./pages/Settings";
import Studio from "./pages/Studio";
import Upload from "./pages/Upload";
import { Spinner } from "./ui";

const MeCtx = createContext<Me | null>(null);
export const useMe = () => useContext(MeCtx)!;

export default function App() {
  const cfg = useQuery({ queryKey: ["config"], queryFn: () => api<Config>("/config") });
  const me = useQuery({
    queryKey: ["me"],
    queryFn: () => api<Me>("/me"),
    enabled: !!cfg.data?.signed_in,
    retry: (n, e) => !(e instanceof ApiError && e.status === 401) && n < 2,
  });
  if (cfg.isLoading || (cfg.data?.signed_in && me.isLoading)) {
    return (
      <div className="grid min-h-screen place-items-center">
        <Spinner />
      </div>
    );
  }
  if (cfg.isError) {
    return <div className="grid min-h-screen place-items-center text-sm text-muted">Could not reach the wardrobe server.</div>;
  }
  if (!cfg.data!.signed_in || (me.error instanceof ApiError && me.error.status === 401) || !me.data) {
    return <Login cfg={cfg.data!} />;
  }
  return (
    <MeCtx.Provider value={me.data}>
      <Layout>
        <Routes>
          <Route path="/" element={<Closet />} />
          <Route path="/item/:id" element={<ItemPage />} />
          <Route path="/photo/:id" element={<PhotoPage />} />
          <Route path="/upload" element={<Upload />} />
          <Route path="/inbox" element={<Inbox />} />
          <Route path="/inbox/:id" element={<BatchReview />} />
          <Route path="/studio" element={<Studio />} />
          <Route path="/settings" element={<Settings />} />
          <Route path="*" element={<Navigate to="/" replace />} />
        </Routes>
      </Layout>
    </MeCtx.Provider>
  );
}
