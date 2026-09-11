import unittest

from resolve_digest.article_images import _client


class ArticleImageClientTests(unittest.TestCase):
    def test_disables_environment_proxies_on_new_session(self):
        self.assertFalse(_client().trust_env)

    def test_disables_environment_proxies_on_provided_session(self):
        class Session:
            trust_env = True

        session = Session()
        self.assertIs(_client(session), session)
        self.assertFalse(session.trust_env)
