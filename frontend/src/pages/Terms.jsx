// V1 Terms of Service — boilerplate that passes Stripe/Google scrutiny but
// SHOULD BE REVIEWED BY A LAWYER before launch. Effective date is tied to
// the file's last commit; revise via PR when material changes ship.
import Footer from '../components/Footer';
import useSEO from '../hooks/useSEO';

export default function Terms() {
  useSEO({
    title: 'Terms of Service | Eidolum',
    description: 'Eidolum Terms of Service — the rules that govern how you use the site.',
  });

  return (
    <div>
      <div className="max-w-3xl mx-auto px-4 sm:px-6 py-10 sm:py-16">
        <h1 className="font-bold text-2xl sm:text-3xl mb-2">Terms of Service</h1>
        <p className="text-text-secondary text-xs mb-8">Last updated: June 2, 2026</p>

        <section className="prose prose-invert mb-8">
          <p className="text-text-secondary leading-relaxed">
            These Terms of Service ("Terms") govern your access to and use of Eidolum
            (eidolum.com and any related applications, the "Service"). By accessing the
            Service you agree to be bound by these Terms.
          </p>
        </section>

        <section className="mb-8">
          <h2 className="font-bold text-lg mb-3">1. What Eidolum is</h2>
          <p className="text-sm text-text-secondary leading-relaxed">
            Eidolum is a data-driven leaderboard that tracks publicly-made financial
            predictions (analyst ratings, social-media calls, and similar) and scores them
            against actual market outcomes. The Service is informational. Nothing on the
            Service is investment advice, an offer to buy or sell any security, or a
            recommendation tailored to your circumstances.
          </p>
        </section>

        <section className="mb-8">
          <h2 className="font-bold text-lg mb-3">2. Not investment advice</h2>
          <p className="text-sm text-text-secondary leading-relaxed">
            All information, analytics, scoring, and rankings are provided "as is" for
            general informational purposes only. You are solely responsible for your own
            investment decisions. We are not a registered investment adviser,
            broker-dealer, or financial planner. Past performance — including any accuracy
            score or return figure shown on Eidolum — does not guarantee future results.
          </p>
        </section>

        <section className="mb-8">
          <h2 className="font-bold text-lg mb-3">3. Your account</h2>
          <p className="text-sm text-text-secondary leading-relaxed">
            If you create an account, you are responsible for keeping your credentials
            secure and for all activity that occurs under your account. You must be at
            least 18 years old (or the age of majority where you live) to create an
            account. You agree to provide accurate information and to keep it current.
          </p>
        </section>

        <section className="mb-8">
          <h2 className="font-bold text-lg mb-3">4. Acceptable use</h2>
          <ul className="list-disc list-inside text-sm text-text-secondary leading-relaxed space-y-1">
            <li>Don't scrape, mirror, or republish bulk data from the Service without written permission.</li>
            <li>Don't attempt to interfere with the Service, its security, or other users' access.</li>
            <li>Don't use the Service to violate any law, regulation, or third-party right.</li>
            <li>Don't impersonate another person, forecaster, or firm.</li>
          </ul>
        </section>

        <section className="mb-8">
          <h2 className="font-bold text-lg mb-3">5. Content & intellectual property</h2>
          <p className="text-sm text-text-secondary leading-relaxed">
            The Service, including its design, software, scoring methodology, and
            aggregated data, is owned by Eidolum and protected by intellectual-property
            law. The underlying predictions are public statements by their original
            authors; we credit each source. You retain ownership of any predictions you
            personally submit to the Service.
          </p>
        </section>

        <section className="mb-8">
          <h2 className="font-bold text-lg mb-3">6. Third-party content & links</h2>
          <p className="text-sm text-text-secondary leading-relaxed">
            The Service surfaces predictions originally made on platforms we don't
            control (financial-news outlets, YouTube, X, etc.). We are not responsible
            for the accuracy, completeness, or availability of third-party content.
            Links to external sites are provided for convenience.
          </p>
        </section>

        <section className="mb-8">
          <h2 className="font-bold text-lg mb-3">7. No warranty</h2>
          <p className="text-sm text-text-secondary leading-relaxed">
            The Service is provided on an "as is" and "as available" basis, without
            warranties of any kind, express or implied, including merchantability,
            fitness for a particular purpose, or non-infringement. We don't warrant that
            the Service will be uninterrupted, error-free, or that any data shown will
            be accurate or current.
          </p>
        </section>

        <section className="mb-8">
          <h2 className="font-bold text-lg mb-3">8. Limitation of liability</h2>
          <p className="text-sm text-text-secondary leading-relaxed">
            To the maximum extent permitted by law, Eidolum and its operators will not be
            liable for any indirect, incidental, special, consequential, or punitive
            damages, or any loss of profits or revenues, arising out of your use of the
            Service — even if we have been advised of the possibility. Our total liability
            for any claim arising from the Service is capped at one hundred US dollars
            (USD $100) or the amount you paid us in the prior twelve months, whichever
            is greater.
          </p>
        </section>

        <section className="mb-8">
          <h2 className="font-bold text-lg mb-3">9. Termination</h2>
          <p className="text-sm text-text-secondary leading-relaxed">
            We may suspend or terminate your access to the Service at any time if you
            violate these Terms or engage in conduct that could harm Eidolum or other
            users. You may stop using the Service and delete your account at any time.
          </p>
        </section>

        <section className="mb-8">
          <h2 className="font-bold text-lg mb-3">10. Changes</h2>
          <p className="text-sm text-text-secondary leading-relaxed">
            We may update these Terms from time to time. Material changes will be
            announced on the Service or via email to your account. Continued use after
            changes take effect constitutes acceptance.
          </p>
        </section>

        <section className="mb-8">
          <h2 className="font-bold text-lg mb-3">11. Governing law</h2>
          <p className="text-sm text-text-secondary leading-relaxed">
            These Terms are governed by the laws of the State of Delaware, USA, without
            regard to its conflict-of-law principles. Any dispute will be resolved
            exclusively in the state or federal courts located in Wilmington, Delaware.
          </p>
        </section>

        <section>
          <h2 className="font-bold text-lg mb-3">12. Contact</h2>
          <p className="text-sm text-text-secondary leading-relaxed">
            Questions about these Terms? Email{' '}
            <a href="mailto:hello@eidolum.com" className="text-accent">hello@eidolum.com</a>.
          </p>
        </section>
      </div>
      <Footer />
    </div>
  );
}
