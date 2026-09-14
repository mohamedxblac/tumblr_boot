"""Small Selenium-compatible helpers used by the BiDi browser adapter.

The bot no longer starts Selenium or GeckoDriver.  These classes keep the
existing scraper and messenger code readable while polling our own BiDi driver.
"""

import time


class By:
    CSS_SELECTOR = "css selector"
    XPATH = "xpath"
    TAG_NAME = "tag name"


class Keys:
    ENTER = "\ue007"
    SHIFT = "\ue008"


class WebDriverWait:
    def __init__(self, driver, timeout, poll_frequency=0.25):
        self.driver = driver
        self.timeout = float(timeout)
        self.poll_frequency = float(poll_frequency)

    def until(self, method):
        deadline = time.monotonic() + self.timeout
        last_error = None
        while time.monotonic() < deadline:
            try:
                result = method(self.driver)
                if result:
                    return result
            except Exception as error:
                last_error = error
            time.sleep(self.poll_frequency)
        if last_error:
            raise TimeoutError(str(last_error)) from last_error
        raise TimeoutError(f"Condition was not met within {self.timeout:.1f} seconds")


class expected_conditions:
    @staticmethod
    def presence_of_element_located(locator):
        return lambda driver: driver.find_element(*locator)

    @staticmethod
    def element_to_be_clickable(locator):
        def predicate(driver):
            element = driver.find_element(*locator)
            return element if element.is_displayed() and element.is_enabled() else False

        return predicate


EC = expected_conditions
