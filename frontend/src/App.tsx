import { Route, Routes } from "react-router-dom";

import { Footer } from "./components/Footer";
import { NavBar } from "./components/NavBar";
import DocumentsPage from "./pages/DocumentsPage";
import DocumentDetailPage from "./pages/DocumentDetailPage";
import LandingPage from "./pages/LandingPage";
import UploadPage from "./pages/UploadPage";

/**
 * One shared shell for every page: the background gradient, header, and footer live here exactly
 * once, and `main` stretches so the footer sits at the viewport bottom even on short pages.
 * Pages render only their content inside their own width container.
 */
export default function App() {
  return (
    <div className="flex min-h-screen flex-col bg-[linear-gradient(to_bottom,#F5F6F1,#EEF2EA)]">
      <NavBar />
      <main className="flex-1">
        <Routes>
          <Route path="/" element={<LandingPage />} />
          <Route path="/upload" element={<UploadPage />} />
          <Route path="/documents" element={<DocumentsPage />} />
          <Route path="/documents/:documentId" element={<DocumentDetailPage />} />
        </Routes>
      </main>
      <Footer />
    </div>
  );
}
