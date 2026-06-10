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
        <p className="text-text-secondary text-xs mb-8">Last updated: June 10, 2026</p>

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
            <strong>Cookies &amp; device storage.</strong> We store data in your
            browser's localStorage and sessionStorage. This is limited to: (1)
            authentication and session data (your sign-in token and basic account
            info, so you stay signed in); (2) interface preferences (your theme
            choice, dismissed banners, and onboarding state); and (3) cached
            application data (your follows, watchlist, and saved predictions, so
            pages load faster). Third-party providers may set strictly-necessary
            cookies during sign-in (e.g., Google OAuth). We do not run advertising
            trackers or third-party analytics, and we do not use cookies or device
            storage to track you across other sites.
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
          <h2 className="font-bold text-lg mb-3">8. YouTube API Services</h2>
          <p className="text-sm text-text-secondary leading-relaxed mb-3">
            Eidolum uses YouTube API Services. In addition to this policy, Google's
            handling of data is described in the{' '}
            <a
              href="http://www.google.com/policies/privacy"
              target="_blank"
              rel="noopener noreferrer"
              className="text-accent"
            >
              Google Privacy Policy
            </a>{' '}
            (http://www.google.com/policies/privacy).
          </p>
          <p className="text-sm text-text-secondary leading-relaxed mb-3">
            <strong>What we access, collect, and store.</strong> Through YouTube API
            Services we access, collect, and store public channel metadata (channel
            name, channel ID, and handle) and public video metadata (video ID, title,
            and publish date) from the channels we track. We use this data to
            attribute public market predictions to the creators who made them and to
            display accuracy statistics for those predictions.
          </p>
          <p className="text-sm text-text-secondary leading-relaxed mb-3">
            <strong>How it is used, processed, and shared.</strong> This data is
            displayed publicly on eidolum.com as part of forecaster profiles and
            leaderboards. It is processed on the infrastructure providers we use to
            run the Service (hosting and database). It is not sold, and it is not
            shared with third parties beyond those infrastructure processors.
          </p>
          <p className="text-sm text-text-secondary leading-relaxed mb-3">
            <strong>No private YouTube data.</strong> Eidolum does not request or
            access private or authorized YouTube user data. We do not ask you to
            connect a YouTube or Google account, and we only process public metadata.
          </p>
          <p className="text-sm text-text-secondary leading-relaxed">
            <strong>Refresh, deletion, and revocation.</strong> Stored YouTube API
            data is refreshed or deleted on a rolling 30-day basis. To request
            deletion of data we obtained via YouTube API Services, email{' '}
            <a href="mailto:privacy@eidolum.com" className="text-accent">privacy@eidolum.com</a>{' '}
            — emailing us is the deletion mechanism, and we respond within 30 days.
            You can also review and revoke any access you have granted to third-party
            applications (including via your Google account) at the{' '}
            <a
              href="https://myaccount.google.com/connections?filters=3,4"
              target="_blank"
              rel="noopener noreferrer"
              className="text-accent"
            >
              Google security settings page
            </a>{' '}
            (https://myaccount.google.com/connections?filters=3,4).
          </p>
        </section>

        <section className="mb-8">
          <h2 className="font-bold text-lg mb-3">9. Children</h2>
          <p className="text-sm text-text-secondary leading-relaxed">
            The Service is not directed to children under 13 and we do not knowingly
            collect personal data from them. If you believe a child has provided us
            personal data, email{' '}
            <a href="mailto:privacy@eidolum.com" className="text-accent">privacy@eidolum.com</a>
            {' '}and we'll delete it.
          </p>
        </section>

        <section className="mb-8">
          <h2 className="font-bold text-lg mb-3">10. Changes to this policy</h2>
          <p className="text-sm text-text-secondary leading-relaxed">
            We may update this policy. Material changes will be announced on the
            Service or via email. The "Last updated" date above always reflects the
            current version.
          </p>
        </section>

        <section>
          <h2 className="font-bold text-lg mb-3">11. Contact</h2>
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
