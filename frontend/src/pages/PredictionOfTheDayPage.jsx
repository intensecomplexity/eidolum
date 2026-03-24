import { Link } from 'react-router-dom';
import { ArrowLeft } from 'lucide-react';
import PredictionOfTheDay from '../components/PredictionOfTheDay';
import Footer from '../components/Footer';

export default function PredictionOfTheDayPage() {
  return (
    <div>
      <div className="max-w-3xl mx-auto px-4 sm:px-6 lg:px-8 py-6 sm:py-10">
        <Link
          to="/"
          className="inline-flex items-center gap-1 text-muted text-sm active:text-text-primary transition-colors mb-4 sm:mb-6 min-h-[44px]"
        >
          <ArrowLeft className="w-4 h-4" /> Back to home
        </Link>

        <PredictionOfTheDay />
      </div>
      <Footer />
    </div>
  );
}
