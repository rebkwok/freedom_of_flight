/*
  This file must be imported immediately-before the close-</body> tag,
  and after JQuery and Underscore.js are imported.
*/
/**
  The number of milliseconds to ignore clicks on the *same* like
  button, after a button *that was not ignored* was clicked. Used by
  `$(document).ready()`.
  Equal to <code>500</code>.
 */
var MILLS_TO_IGNORE = 500;

/**
   Executes a toggle click. Triggered by clicks on the visible button.
 */
var toggleVisible = function()  {

    //In this scope, "this" is the button just clicked on.
    //The "this" in processResult is *not* the button just clicked
    //on.
    var $button_just_clicked_on = $(this);

    //The value of the "data-course_id" attribute.
    var course_id = $button_just_clicked_on.data('course_id');

    var processResult = function(
       result, status, jqXHR)  {
      //console.log("sf result='" + result + "', status='" + status + "', jqXHR='" + jqXHR + "', user_id='" + user_id + "'");
        $('#visible-' + course_id).html(result);
   };

   $.ajax(
       {
          url: '/studioadmin/ajax-toggle-course-visible/' + course_id + '/',
          type: 'POST',
          dataType: 'html',
          success: processResult
          //Should also have a "fail" call as well.
       }
    );
};


var toggleAllowPartialBooking = function()  {

    //In this scope, "this" is the button just clicked on.
    //The "this" in processResult is *not* the button just clicked
    //on.
    var $button_just_clicked_on = $(this);

    //The value of the "data-course_id" attribute.
    var course_id = $button_just_clicked_on.data('course_id');

    var processResult = function(
       result, status, jqXHR)  {
      //console.log("sf result='" + result + "', status='" + status + "', jqXHR='" + jqXHR + "', user_id='" + user_id + "'");
        $('#allow-partial-booking-' + course_id).html(result);
   };

   $.ajax(
       {
          url: '/studioadmin/ajax-toggle-course-allow-partial-booking/' + course_id + '/',
          type: 'POST',
          dataType: 'html',
          success: processResult
          //Should also have a "fail" call as well.
       }
    );
};


var toggleAllowDropinBooking = function()  {

    //In this scope, "this" is the button just clicked on.
    //The "this" in processResult is *not* the button just clicked
    //on.
    var $button_just_clicked_on = $(this);

    //The value of the "data-course_id" attribute.
    var course_id = $button_just_clicked_on.data('course_id');

    var processResult = function(
       result, status, jqXHR)  {
      //console.log("sf result='" + result + "', status='" + status + "', jqXHR='" + jqXHR + "', user_id='" + user_id + "'");
        $('#allow-dropin-booking-' + course_id).html(result);
   };

   $.ajax(
       {
          url: '/studioadmin/ajax-toggle-course-allow-dropin-booking/' + course_id + '/',
          type: 'POST',
          dataType: 'html',
          success: processResult
          //Should also have a "fail" call as well.
       }
    );
};

/**
   The Ajax "main" function. Attaches the listeners to the elements on
   page load, each of which only take effect every
   <link to MILLS_TO_IGNORE> seconds.

   This protection is only against a single user pressing buttons as fast
   as they can. This is in no way a protection against a real DDOS attack,
   of which almost 100% bypass the client (browser) (they instead
   directly attack the server). Hence client-side protection is pointless.

   - http://stackoverflow.com/questions/28309850/how-much-prevention-of-rapid-fire-form-submissions-should-be-on-the-client-side

   The protection is implemented via Underscore.js' debounce function:
  - http://underscorejs.org/#debounce

   Using this only requires importing underscore-min.js. underscore-min.map
   is not needed.
 */
$(document).ready(function()  {
  /*
    There are many buttons having the class

      td_ajax_book_button

    This attaches a listener to *every one*. Calling this again
    would attach a *second* listener to every button, meaning each
    click would be processed twice.
   */
  $('.visible-btn').click(_.debounce(toggleVisible, MILLS_TO_IGNORE, true));
  $('.allow-partial-booking-btn').click(_.debounce(toggleAllowPartialBooking, MILLS_TO_IGNORE, true));
$('.allow-dropin-booking-btn').click(_.debounce(toggleAllowDropinBooking, MILLS_TO_IGNORE, true));
  /*
    Warning: Placing the true parameter outside of the debounce call:

    $('#color_search_text').keyup(_.debounce(processSearch,
        MILLS_TO_IGNORE_SEARCH), true);

    results in "TypeError: e.handler.apply is not a function".
   */

});