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
var MILLS_TO_IGNORE = 1000;


var processCheckoutRequest = function()  {

    //In this scope, "this" is the button just clicked on.
    //The "this" in processResult is *not* the button just clicked
    //on.
    var $button_just_clicked_on = $(this);
    var cart_total = $button_just_clicked_on.data('total');

    var processResult = function(result, status, jqXHR)  {
      //console.log("sf result='" + result + "', status='" + status + "', jqXHR='" + jqXHR + "'");

      if (result.redirect) {
          window.location = result.url;
      } else {
        $("#loader").removeClass("fa fa-spinner fa-spin").hide();
        $('#checkout-btn').hide();
        $('#paypal-checkout-btn').html(result.paypal_form_html);
        $('#submit_paypal').click();
        }
    };

    var processFailure = function(result, status, jqXHR)  {
      //console.log("sf result='" + result + "', status='" + status + "', jqXHR='" + jqXHR + "'");
      if (result.responseText) {
        vNotify.error({text:result.responseText,title:'Error',position: 'bottomRight'});
      }
   };

   $.ajax(
       {
          url: '/ajax-checkout/',
          dataType: 'json',
          type: 'POST',
          data: {csrfmiddlewaretoken: window.CSRF_TOKEN, "cart_total": cart_total},
          beforeSend: function() {
              $("#loader").addClass("fa fa-spinner fa-spin").show();

          },
          success: processResult,
          //Should also have a "fail" call as well.
          complete: function() {},
          error: processFailure
       }
    );

};


var processRemoveBlock = function()  {

    //In this scope, "this" is the button just clicked on.
    //The "this" in processResult is *not* the button just clicked
    //on.
    var $button_just_clicked_on = $(this);

    //The value of the "data-event_id" attribute.
    var block_id = $button_just_clicked_on.data('block_id');

    var processResult = function(
       result, status, jqXHR)  {
      //console.log("sf result='" + result + "', status='" + status + "', jqXHR='" + jqXHR + "'");
    $('#cart-row-' + block_id).html("");
    $('#cart_item_menu_count').text(result.cart_item_menu_count);
    $('#total').text(result.cart_total);
    $('#checkout-btn').data('total', result.cart_total);
    $('#payment-btn').html(result.payment_button_html);
   };

    var processFailure = function(
       result, status, jqXHR)  {
      //console.log("sf result='" + result + "', status='" + status + "', jqXHR='" + jqXHR + "'");
      if (result.responseText) {
        vNotify.error({text:result.responseText,title:'Error',position: 'bottomRight'});
      }
   };

   $.ajax(
       {
          url: '/ajax-block-delete/' + block_id + "/",
          dataType: 'json',
          type: 'POST',
          data: {csrfmiddlewaretoken: window.CSRF_TOKEN},
          success: processResult,
          //Should also have a "fail" call as well.
          error: processFailure
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
  $('.ajax-checkout-btn').click(_.debounce(processCheckoutRequest, MILLS_TO_IGNORE, true));

  $('.remove-block').click(_.debounce(processRemoveBlock, MILLS_TO_IGNORE, true));

  // delegate events for the paypal form input
  $( "#paypal-btn-wrapper" ).on('click', 'input[type=image]', function( event ) {
    console.log("Submitted the go to paypal form");
});

  /*
    Warning: Placing the true parameter outside of the debounce call:

    $('#color_search_text').keyup(_.debounce(processSearch,
        MILLS_TO_IGNORE_SEARCH), true);

    results in "TypeError: e.handler.apply is not a function".
   */

});