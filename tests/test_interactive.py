"""
Tests for interactive input prompts, URL validation, and integer bounds.
"""

import unittest
from unittest.mock import patch
from main import prompt_validated_url, prompt_validated_int


class TestInteractiveInput(unittest.TestCase):

    @patch("builtins.input", side_effect=["https://example.com"])
    def test_prompt_valid_url(self, mock_input):
        url = prompt_validated_url()
        self.assertEqual(url, "https://example.com")

    @patch("builtins.input", side_effect=["example.com"])
    def test_prompt_url_auto_prefix(self, mock_input):
        url = prompt_validated_url()
        self.assertEqual(url, "https://example.com")

    @patch("builtins.input", side_effect=["", "not a url", "http://valid.org/test"])
    def test_prompt_invalid_then_valid_url(self, mock_input):
        url = prompt_validated_url()
        self.assertEqual(url, "http://valid.org/test")

    @patch("builtins.input", side_effect=["5"])
    def test_prompt_valid_int(self, mock_input):
        val = prompt_validated_int("Enter number of threads:", min_val=1)
        self.assertEqual(val, 5)

    @patch("builtins.input", side_effect=[""])
    def test_prompt_default_int(self, mock_input):
        val = prompt_validated_int("Enter number of threads:", min_val=1, default_val=4)
        self.assertEqual(val, 4)

    @patch("builtins.input", side_effect=["-2", "abc", "3"])
    def test_prompt_invalid_then_valid_int(self, mock_input):
        val = prompt_validated_int("Enter depth:", min_val=0)
        self.assertEqual(val, 3)


if __name__ == "__main__":
    unittest.main()
