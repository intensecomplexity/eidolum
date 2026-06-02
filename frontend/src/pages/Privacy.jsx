// V1 Privacy Policy — boilerplate covering GDPR/CCPA basics. SHOULD BE
// REVIEWED BY A LAWYER before launch, especially the EU/UK/CA-resident
// sections if material EU traffic is expected.
import Footer from '../components/Footer';
import useSEO from '../hooks/useSEO';

export default function Privacy() {
  useSEO({
    title: 'Privacy Policy | Eidolum',
    description: 'Eidolum Privacy Policy — what we collect, why, and how to control it.',
  });

  return (
    <div>
      <div className="max-w-3xl mx-auto px-4 sm:px-6 py-10 sm:py-16">
        <h1 className="font-bold text-2xl sm:text-3xl mb-2">Privacy Policy</h1>
        <p className="text-text-secondary text-xs mb-8">Last updated: June 2, 2026</p>

        <section className="mb-8">
          <p className="text-text-secondary text-sm leading-relaxed">
            This Privacy Policy explains what data Eidolum collects, why we collect it,
            and the choices you have. By using the Service you agree to this policy.
          </p>
        </section>

        <section className="mb-8">
          <h2 className="font-bold text-lg mb-3">1. What we collect</h2>
          <p className="text-sm text-text-secondary leading-relaxed mb-3">
            <strong>Account data.</strong> When you create an account we store your
            email, a hashed password, and any profile fields you choose to fill in.
          </p>
          <p className="text-sm text-text-secondary leading-relaxed mb-3">
            <strong>Usage data.</strong> We log basic technical events when you use the
            Service: page views, API requests, IP address, browser/user-agent,
            referrer, and approximate location (derived from IP). This lets us debug
            errors, prevent abuse, and understand which pages are useful.
          </p>
          <p className="text-sm text-text-secondary leading-relaxed mb-3">
            <strong>Predictions you submit.</strong> If you submit your own predictions,
            we store them so they can be scored against market outcomes and displayed
            on your profile.
          </p>
          <p className="text-sm text-text-secondary leading-relaxed">
            <strong>Cookies.</strong> We use first-party cookies for authentication and
            preference storage. We may use a small number of strictly-necessary
            third-party cookies (e.g., for sign-in via OAuth providers). We do not run
            advertising trackers.
          </p>
        </section>

        <section className="mb-8">
          <h2 className="font-bold text-lg mb-3">2. Why we collect it</h2>
          <ul className="list-disc list-inside text-sm text-text-secondary leading-relaxed space-y-1">
            <li>To operate and improve the Service.</li>
            <li>To authenticate you and keep your account secure.</li>
            <li>To prevent abuse, fraud, and unauthorized access.</li>
            <li>To respond to your support requests.</li>
            <li>To comply with legal obligations.</li>
          </ul>
        </section>

        <section className="mb-8">
          <h2 className="font-bold text-lg mb-3">3. How we share it</h2>
          <p className="text-sm text-text-secondary leading-relaxed mb-3">
            We don't sell your personal data. We share data only with:
          </p>
          <ul className="list-disc list-inside text-sm text-text-secondary leading-relaxed space-y-1">
            <li><strong>Infrastructure providers</strong> we use to run the Service (hosting, database, email delivery, error monitoring). They process data on our behalf under contracts that restrict their use of it.</li>
            <li><strong>Authentication providers</strong> (e.g., Google) when you choose to sign in via OAuth.</li>
            <li><strong>Law enforcement</strong> when legally required, narrowly limited to what the request demands.</li>
          </ul>
        </section>

        <section className="mb-8">
          <h2 className="font-bold text-lg mb-3">4. How long we keep it</h2>
          <p className="text-sm text-text-secondary leading-relaxed">
            We keep account data for as long as your account is active. If you delete
            your account, we delete or anonymize your personal data within 30 days
            (we may retain anonymous, aggregate data and limited records required for
            tax, legal, or fraud-prevention purposes). Usage logs are typically rotated
            within 90 days.
          </p>
        </section>

        <section className="mb-8">
          <h2 className="font-bold text-lg mb-3">5. Your rights</h2>
          <p className="text-sm text-text-secondary leading-relaxed mb-3">
            Depending on where you live (EU/UK/California in particular), you may have
            the right to:
          </p>
          <ul className="list-disc list-inside text-sm text-text-secondary leading-relaxed space-y-1">
            <li>Access the personal data we hold about you.</li>
            <li>Correct inaccurate data.</li>
            <li>Delete your data ("right to be forgotten").</li>
            <li>Export your data in a machine-readable format.</li>
            <li>Object to certain processing.</li>
          </ul>
          <p className="text-sm text-text-secondary leading-relaxed mt-3">
            To exercise any of these, email{' '}
            <a href="mailto:privacy@eidolum.com" className="text-accent">privacy@eidolum.com</a>.
            We respond within 30 days.
          </p>
        </section>

        <section className="mb-8">
          <h2 className="font-bold text-lg mb-3">6. Security</h2>
          <p className="text-sm text-text-secondary leading-relaxed">
            We use industry-standard encryption (TLS) in transit and at rest. Passwords
            are hashed with a modern adaptive algorithm. We restrict access to personal
            data to engineers with a legitimate operational need. Despite this, no
            system is 100% secure, and we can't guarantee absolute security.
          </p>
        </section>

        <section className="mb-8">
          <h2 className="font-bold text-lg mb-3">7. International transfers</h2>
          <p className="text-sm text-text-secondary leading-relaxed">
            Our infrastructure is hosted in the United States. If you access the
            Service from outside the US, your data is transferred to and processed
            there under contractual safeguards required by applicable law.
          </p>
        </section>

        <section className="mb-8">
          <h2 className="font-bold text-lg mb-3">8. Children</h2>
          <p className="text-sm text-text-secondary leading-relaxed">
            The Service is not directed to children under 13 and we do not knowingly
            collect personal data from them. If you believe a child has provided us
            personal data, email{' '}
            <a href="mailto:privacy@eidolum.com" className="text-accent">privacy@eidolum.com</a>
            {' '}and we'll delete it.
          </p>
        </section>

        <section className="mb-8">
          <h2 className="font-bold text-lg mb-3">9. Changes to this policy</h2>
          <p className="text-sm text-text-secondary leading-relaxed">
            We may update this policy. Material changes will be announced on the
            Service or via email. The "Last updated" date above always reflects the
            current version.
          </p>
        </section>

        <section>
          <h2 className="font-bold text-lg mb-3">10. Contact</h2>
          <p className="text-sm text-text-secondary leading-relaxed">
            Privacy questions:{' '}
            <a href="mailto:privacy@eidolum.com" className="text-accent">privacy@eidolum.com</a>.
            General inquiries:{' '}
            <a href="mailto:hello@eidolum.com" className="text-accent">hello@eidolum.com</a>.
          </p>
        </section>
      </div>
      <Footer />
    </div>
  );
}
